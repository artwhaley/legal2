import 'package:evw_client/src/evw_database.dart';
import 'package:evw_client/src/evw_models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqlite3/sqlite3.dart';

void main() {
  test('printable artifacts create the default group lazily and preserve order', () {
    final raw = sqlite3.openInMemory();
    addTearDown(raw.dispose);
    raw.execute('''
      CREATE TABLE workspace_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      INSERT INTO workspace_state VALUES ('updated_at','');
      CREATE TABLE working_corpus(working_corpus_id INTEGER PRIMARY KEY,dataset_id INTEGER,name TEXT,current_revision_id INTEGER);
      CREATE TABLE working_corpus_revision(working_corpus_revision_id INTEGER PRIMARY KEY,working_corpus_id INTEGER,revision_number INTEGER,status TEXT,message_count INTEGER,estimated_tokens INTEGER,scope_hash TEXT);
      CREATE TABLE working_corpus_revision_index(working_corpus_revision_id INTEGER,index_generation INTEGER,status TEXT,fts_status TEXT,message_embedding_status TEXT,chunk_embedding_status TEXT);
      CREATE TABLE source_thread(source_thread_id TEXT PRIMARY KEY,display_title TEXT);
      CREATE TABLE message(message_id TEXT PRIMARY KEY,source_thread_id TEXT,timestamp TEXT,sender_display TEXT,body TEXT);
      CREATE TABLE working_corpus_revision_message(working_corpus_revision_id INTEGER,message_id TEXT,source_thread_id TEXT,ordinal INTEGER,token_count INTEGER,embedding_input_hash TEXT,PRIMARY KEY(working_corpus_revision_id,message_id));
      CREATE TABLE category(category_id INTEGER PRIMARY KEY,dataset_id INTEGER,name TEXT);
      CREATE TABLE evidence_block(evidence_block_id INTEGER PRIMARY KEY,dataset_id INTEGER,category_id INTEGER,source_thread_id TEXT,title TEXT,summary TEXT,context_start_message_id TEXT,relevant_start_message_id TEXT,core_message_id TEXT,relevant_end_message_id TEXT,context_end_message_id TEXT,origin_kind TEXT,origin_working_corpus_revision_id INTEGER,origin_scope_hash TEXT);
      CREATE TABLE evidence_block_message(evidence_block_id INTEGER,message_id TEXT,ordinal INTEGER,section TEXT,message_content_hash TEXT,PRIMARY KEY(evidence_block_id,message_id));
      CREATE TABLE evidence_block_highlight(evidence_block_id INTEGER,message_id TEXT,PRIMARY KEY(evidence_block_id,message_id));
      CREATE TABLE working_corpus_revision_evidence_block(working_corpus_revision_id INTEGER,evidence_block_id INTEGER,inherited_from_revision_id INTEGER,associated_at TEXT,PRIMARY KEY(working_corpus_revision_id,evidence_block_id));
      CREATE TABLE printable_artifact_group(printable_artifact_group_id INTEGER PRIMARY KEY AUTOINCREMENT,dataset_id INTEGER,name TEXT,sort_order INTEGER,is_collapsed INTEGER,created_at TEXT,updated_at TEXT);
      CREATE TABLE printable_artifact(printable_artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,dataset_id INTEGER,group_id INTEGER,title TEXT,exhibit_number TEXT,case_number TEXT,sort_order INTEGER,created_at TEXT,updated_at TEXT);
      CREATE TABLE printable_artifact_evidence_block(printable_artifact_evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,printable_artifact_id INTEGER,evidence_block_id INTEGER,sort_order INTEGER,created_at TEXT);
    ''');
    raw.execute("INSERT INTO working_corpus VALUES (1,1,'Corpus',1)");
    raw.execute(
      "INSERT INTO working_corpus_revision VALUES (1,1,1,'ready',3,3,'scope')",
    );
    raw.execute(
      "INSERT INTO working_corpus_revision_index VALUES (1,1,'ready','ready','ready','ready')",
    );
    raw.execute("INSERT INTO source_thread VALUES ('thread','Thread')");
    for (var index = 1; index <= 3; index++) {
      raw.execute('INSERT INTO message VALUES (?,?,?,?,?)', [
        'm$index',
        'thread',
        '2026-01-01T00:0${index}:00Z',
        'Sender',
        'Body $index',
      ]);
      raw.execute(
        'INSERT INTO working_corpus_revision_message VALUES (?,?,?,?,?,?)',
        [1, 'm$index', 'thread', index - 1, 1, 'hash$index'],
      );
    }
    raw.execute("INSERT INTO category VALUES (1,1,'Uncategorized')");
    _insertEvidence(raw, 1, 'First block', 'm1', 'm2', 'm3');
    _insertEvidence(raw, 2, 'Second block', 'm2', 'm2', 'm3');
    raw.execute("INSERT INTO working_corpus VALUES (2,1,'Other corpus',2)");
    raw.execute(
      "INSERT INTO working_corpus_revision VALUES (2,2,1,'ready',3,3,'other-scope')",
    );
    raw.execute(
      "INSERT INTO working_corpus_revision_index VALUES (2,1,'ready','ready','ready','ready')",
    );
    for (var index = 1; index <= 3; index++) {
      raw.execute(
        'INSERT INTO working_corpus_revision_message VALUES (?,?,?,?,?,?)',
        [2, 'm$index', 'thread', index - 1, 1, 'hash$index'],
      );
    }
    _insertEvidence(
      raw,
      3,
      'Other corpus block',
      'm1',
      'm2',
      'm3',
      revisionId: 2,
    );
    final database = EvwDatabase.forTesting(raw);
    final groupsBefore = database.printableArtifactGroups(1);
    expect(groupsBefore, isEmpty);

    final first = database.createPrintableArtifactFromEvidence(
      revisionId: 1,
      evidenceBlockId: 1,
    );
    expect(database.printableArtifactGroups(1).single.name, 'Default');
    expect(first.blocks.single.messages.map((message) => message.id), [
      'm1',
      'm2',
      'm3',
    ]);
    expect(
      first.blocks.single.evidence.isRelevant(
        TranscriptMessage(
          id: 'm2',
          threadId: 'thread',
          threadTitle: 'Thread',
          ordinal: 1,
          timestamp: '',
          sender: '',
          body: '',
        ),
      ),
      isTrue,
    );

    final updated = database.updatePrintableArtifactMetadata(
      datasetId: 1,
      artifactId: first.artifact.id,
      title: 'Exhibit title',
      exhibitNumber: 'A',
      caseNumber: 'Case 1',
    );
    expect(updated.title, 'Exhibit title');
    database.appendPrintableEvidenceBlock(
      revisionId: 1,
      artifactId: first.artifact.id,
      evidenceBlockId: 2,
    );
    expect(
      () => database.appendPrintableEvidenceBlock(
        revisionId: 1,
        artifactId: first.artifact.id,
        evidenceBlockId: 2,
      ),
      throwsStateError,
    );
    var document = database.printableArtifactDocument(
      revisionId: 1,
      artifactId: first.artifact.id,
    );
    expect(document.blocks.map((block) => block.evidence.id), [1, 2]);
    database.movePrintableArtifactBlock(
      datasetId: 1,
      artifactId: first.artifact.id,
      joinId: document.blocks[1].joinId,
      delta: -1,
    );
    document = database.printableArtifactDocument(
      revisionId: 1,
      artifactId: first.artifact.id,
    );
    expect(document.blocks.map((block) => block.evidence.id), [2, 1]);
    database.removePrintableArtifactBlock(
      datasetId: 1,
      artifactId: first.artifact.id,
      joinId: document.blocks.first.joinId,
    );
    expect(
      database
          .printableArtifactDocument(
            revisionId: 1,
            artifactId: first.artifact.id,
          )
          .blocks
          .map((block) => block.evidence.id),
      [1],
    );

    final crossCorpus = database.createPrintableArtifactFromEvidence(
      revisionId: 2,
      evidenceBlockId: 3,
    );
    expect(
      database
          .printableArtifactDocument(
            revisionId: 1,
            artifactId: crossCorpus.artifact.id,
          )
          .blocks
          .single
          .evidence
          .id,
      3,
    );
  });
}

void _insertEvidence(
  Database raw,
  int id,
  String title,
  String contextStart,
  String relevantStart,
  String contextEnd, {
  int revisionId = 1,
}) {
  raw.execute(
    '''INSERT INTO evidence_block(
       evidence_block_id,dataset_id,category_id,source_thread_id,title,summary,
       context_start_message_id,relevant_start_message_id,core_message_id,
       relevant_end_message_id,context_end_message_id,origin_kind,
       origin_working_corpus_revision_id,origin_scope_hash)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
    [
      id,
      1,
      1,
      'thread',
      title,
      'Summary',
      contextStart,
      relevantStart,
      relevantStart,
      contextEnd,
      contextEnd,
      'working_corpus_revision',
      revisionId,
      revisionId == 1 ? 'scope' : 'other-scope',
    ],
  );
  raw.execute(
    'INSERT INTO working_corpus_revision_evidence_block VALUES (?,?,?,?)',
    [revisionId, id, null, '2026-01-01T00:00:00Z'],
  );
  for (var ordinal = 0; ordinal < 3; ordinal++) {
    raw.execute('INSERT INTO evidence_block_message VALUES (?,?,?,?,?)', [
      id,
      'm${ordinal + 1}',
      ordinal,
      ordinal == 1 ? 'relevant' : 'leading_context',
      'hash',
    ]);
  }
  raw.execute('INSERT INTO evidence_block_highlight VALUES (?,?)', [
    id,
    relevantStart,
  ]);
}
