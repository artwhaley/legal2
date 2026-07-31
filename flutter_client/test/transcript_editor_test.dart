import 'dart:io';

import 'package:evw_client/src/evw_database.dart';
import 'package:evw_client/src/evw_models.dart';
import 'package:evw_client/src/transcript_editor.dart';
import 'package:evw_client/src/transcript_height_index.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqlite3/sqlite3.dart' show Database, sqlite3;

void main() {
  test('height index maps variable-height messages without fixed rows', () {
    final index = TranscriptHeightIndex(4, defaultHeight: 100);
    expect(index.totalHeight, 400);
    index.setHeight(1, 240);
    expect(index.totalHeight, 540);
    expect(index.offsetForOrdinal(2), 340);
    expect(index.ordinalForOffset(339), 1);
    expect(index.ordinalForOffset(340), 2);
    expect(index.measuredCount, 1);
  });

  test('FTS search is scoped, paginated, and rejects empty terms', () {
    final fixture = _Fixture(messageCount: 12);
    addTearDown(fixture.close);

    final first = fixture.database.ftsSearch(
      fixture.revision.id,
      'message',
      indexGeneration: 1,
      limit: 5,
    );
    expect(first.hits, hasLength(5));
    expect(first.totalCount, 12);
    expect(first.hasMore, isTrue);
    expect(first.nextOffset, 5);
    expect(first.hits.map((hit) => hit.ordinal), [0, 1, 2, 3, 4]);

    final second = fixture.database.ftsSearch(
      fixture.revision.id,
      'message',
      indexGeneration: 1,
      limit: 100,
      offset: first.nextOffset!,
    );
    expect(second.hits.map((hit) => hit.ordinal), [5, 6, 7, 8, 9, 10, 11]);
    expect(
      () => fixture.database.ftsSearch(1, '   ', indexGeneration: 1),
      throwsArgumentError,
    );
  });

  test(
    'evidence editing persists exact same-thread messages and every field',
    () {
      final fixture = _Fixture(messageCount: 12, interleaveThreads: true);
      addTearDown(fixture.close);

      final revision = fixture.revision;
      final controller = TranscriptDocumentController(
        database: fixture.database,
        revision: revision,
      )..reload();

      final created = controller.createAtOrdinal(4);
      expect(created.sourceThreadId, 'thread-a');
      expect(created.coreMessageId, 'm004');
      expect(created.messageIds, everyElement(startsWith('m')));
      expect(
        created.messageIds
            .map((id) => fixture.database.ordinalForMessage(revision.id, id)!)
            .every((ordinal) => ordinal.isEven),
        isTrue,
      );
      expect(created.highlightedMessageIds, {'m004'});

      controller.previewBoundary(EvidenceBoundary.contextStart, 0);
      controller.previewBoundary(EvidenceBoundary.relevantStart, 2);
      controller.previewBoundary(EvidenceBoundary.relevantEnd, 8);
      controller.previewBoundary(EvidenceBoundary.contextEnd, 10);
      controller.persistBoundaryEdit();
      controller.setPrimaryMessage('m006');
      controller.toggleHighlight('m008');
      controller.saveMetadata(
        'School disagreement',
        'A concise human-written summary.',
      );

      final stored = fixture.database.evidenceBlock(revision.id, created.id);
      expect(stored.contextStartMessageId, 'm000');
      expect(stored.relevantStartMessageId, 'm002');
      expect(stored.coreMessageId, 'm006');
      expect(stored.relevantEndMessageId, 'm008');
      expect(stored.contextEndMessageId, 'm010');
      expect(stored.title, 'School disagreement');
      expect(stored.summary, 'A concise human-written summary.');
      expect(stored.highlightedMessageIds, containsAll(['m004', 'm008']));
      expect(stored.sections['m000'], 'leading_context');
      expect(stored.sections['m002'], 'relevant');
      expect(stored.sections['m008'], 'relevant');
      expect(stored.sections['m010'], 'trailing_context');

      final hashes = fixture.raw.select(
        'SELECT message_content_hash FROM evidence_block_message WHERE evidence_block_id=?',
        [stored.id],
      );
      expect(hashes, isNotEmpty);
      expect(
        hashes.every(
          (row) => (row['message_content_hash'] as String).length == 64,
        ),
        isTrue,
      );

      final otherThread = fixture.database.messageAtOrdinal(revision.id, 5)!;
      final annotation = controller.annotationFor(otherThread);
      expect(annotation.context, isFalse);
      expect(annotation.relevant, isFalse);

      controller.setHidden(stored.id, true);
      expect(controller.annotationFor(fixture.message(6)).relevant, isFalse);
      expect(
        fixture.database.evidenceBlock(revision.id, stored.id).messageIds,
        stored.messageIds,
      );
      controller.setHidden(stored.id, false);
      expect(controller.annotationFor(fixture.message(6)).relevant, isTrue);
      controller.selectBlock(stored.id);
      controller.deleteActiveBlock();
      expect(controller.blocks, isEmpty);
      expect(
        fixture.raw.select(
          'SELECT * FROM evidence_block WHERE evidence_block_id=?',
          [stored.id],
        ),
        isEmpty,
      );
    },
  );

  test(
    'active evidence follows the viewport and remains sticky while visible',
    () {
      final fixture = _Fixture(messageCount: 100);
      addTearDown(fixture.close);
      final controller = TranscriptDocumentController(
        database: fixture.database,
        revision: fixture.revision,
      )..reload();
      addTearDown(controller.dispose);
      final first = controller.createAtOrdinal(20);
      final second = controller.createAtOrdinal(60);

      controller.selectBlock(first.id);
      controller.reconcileActiveBlockForViewport(
        visibleStartOrdinal: 15,
        visibleEndOrdinal: 30,
        centerOrdinal: 22,
      );
      expect(controller.activeBlockId, first.id);

      controller.reconcileActiveBlockForViewport(
        visibleStartOrdinal: 50,
        visibleEndOrdinal: 70,
        centerOrdinal: 60,
      );
      expect(controller.activeBlockId, second.id);

      controller.setHidden(second.id, true);
      controller.reconcileActiveBlockForViewport(
        visibleStartOrdinal: 50,
        visibleEndOrdinal: 70,
        centerOrdinal: 60,
      );
      expect(controller.activeBlockId, isNull);
    },
  );

  test('overlapping evidence uses center proximity only when handing off', () {
    final fixture = _Fixture(messageCount: 100);
    addTearDown(fixture.close);
    final controller = TranscriptDocumentController(
      database: fixture.database,
      revision: fixture.revision,
    )..reload();
    addTearDown(controller.dispose);
    final first = controller.createAtOrdinal(20);
    final second = controller.createAtOrdinal(24);

    controller.selectBlock(null);
    controller.reconcileActiveBlockForViewport(
      visibleStartOrdinal: 18,
      visibleEndOrdinal: 28,
      centerOrdinal: 23,
    );
    expect(controller.activeBlockId, second.id);

    controller.reconcileActiveBlockForViewport(
      visibleStartOrdinal: 18,
      visibleEndOrdinal: 28,
      centerOrdinal: 20,
    );
    expect(
      controller.activeBlockId,
      second.id,
      reason: 'The current overlapping block must not flicker away.',
    );

    controller.reconcileActiveBlockForViewport(
      visibleStartOrdinal: 14,
      visibleEndOrdinal: 20,
      centerOrdinal: 18,
    );
    expect(controller.activeBlockId, first.id);
  });

  testWidgets('virtual transcript deep jump keeps message hydration bounded', (
    tester,
  ) async {
    final fixture = _Fixture(messageCount: 1500);
    addTearDown(fixture.close);
    final controller = TranscriptDocumentController(
      database: fixture.database,
      revision: fixture.revision,
    )..reload();
    addTearDown(controller.dispose);
    final key = GlobalKey<VirtualTranscriptViewState>();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 900,
            height: 600,
            child: VirtualTranscriptView(key: key, controller: controller),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(key.currentState, isNotNull);
    expect(key.currentState!.cachedMessageCount, lessThan(1500));

    expect(key.currentState!.scrollToOrdinal(1400), isTrue);
    await tester.pump();
    await tester.pump();
    expect(key.currentState!.visibleStart, lessThanOrEqualTo(1400));
    expect(key.currentState!.visibleEnd, greaterThanOrEqualTo(1400));
    expect(key.currentState!.cachedMessageCount, lessThan(1500));

    final block = controller.createAtOrdinal(1400);
    await tester.pump();
    expect(find.text('Context start'), findsOneWidget);
    expect(find.text('Relevant start'), findsOneWidget);
    expect(find.text('Relevant end'), findsOneWidget);
    expect(find.text('Context end'), findsOneWidget);
    expect(controller.activeBlockId, block.id);
  });

  testWidgets('virtual transcript activates evidence as it is encountered', (
    tester,
  ) async {
    final fixture = _Fixture(messageCount: 1500);
    addTearDown(fixture.close);
    final controller = TranscriptDocumentController(
      database: fixture.database,
      revision: fixture.revision,
    )..reload();
    addTearDown(controller.dispose);
    final first = controller.createAtOrdinal(100);
    final second = controller.createAtOrdinal(1400);
    final key = GlobalKey<VirtualTranscriptViewState>();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 900,
            height: 600,
            child: VirtualTranscriptView(key: key, controller: controller),
          ),
        ),
      ),
    );
    await tester.pump();
    expect(controller.activeBlockId, isNull);

    expect(key.currentState!.scrollToOrdinal(first.coreOrdinal), isTrue);
    await tester.pump();
    await tester.pump();
    expect(controller.activeBlockId, first.id);

    expect(key.currentState!.scrollToOrdinal(second.coreOrdinal), isTrue);
    await tester.pump();
    await tester.pump();
    expect(controller.activeBlockId, second.id);

    controller.setHidden(second.id, true);
    await tester.pump();
    await tester.pump();
    expect(controller.activeBlockId, isNull);
  });

  testWidgets('only the active mounted transcript controls center activation', (
    tester,
  ) async {
    final fixture = _Fixture(messageCount: 400);
    addTearDown(fixture.close);
    final controller = TranscriptDocumentController(
      database: fixture.database,
      revision: fixture.revision,
    )..reload();
    addTearDown(controller.dispose);
    final first = controller.createAtOrdinal(40);
    final second = controller.createAtOrdinal(300);
    final activeKey = GlobalKey<VirtualTranscriptViewState>();
    final inactiveKey = GlobalKey<VirtualTranscriptViewState>();

    await tester.pumpWidget(
      MaterialApp(
        home: Row(
          children: [
            Expanded(
              child: VirtualTranscriptView(
                key: activeKey,
                controller: controller,
                viewportActivationEnabled: true,
              ),
            ),
            Expanded(
              child: VirtualTranscriptView(
                key: inactiveKey,
                controller: controller,
                viewportActivationEnabled: false,
              ),
            ),
          ],
        ),
      ),
    );
    await tester.pump();
    expect(activeKey.currentState!.scrollToOrdinal(first.coreOrdinal), isTrue);
    await tester.pump();
    await tester.pump();
    expect(controller.activeBlockId, first.id);

    expect(
      inactiveKey.currentState!.scrollToOrdinal(second.coreOrdinal),
      isTrue,
    );
    await tester.pump();
    await tester.pump();
    expect(controller.activeBlockId, first.id);

    await tester.pumpWidget(
      MaterialApp(
        home: Row(
          children: [
            Expanded(
              child: VirtualTranscriptView(
                key: activeKey,
                controller: controller,
                viewportActivationEnabled: false,
              ),
            ),
            Expanded(
              child: VirtualTranscriptView(
                key: inactiveKey,
                controller: controller,
                viewportActivationEnabled: true,
              ),
            ),
          ],
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
    expect(controller.activeBlockId, second.id);
  });

  final realEvwPath = Platform.environment['EVW_TRANSCRIPT_TEST_PATH'];
  if (realEvwPath != null && realEvwPath.isNotEmpty) {
    test('real v15 EVW evidence round trip', () {
      final database = EvwDatabase.open(realEvwPath);
      addTearDown(database.close);
      final revision = database.revisions().firstWhere(
        (item) => item.status == 'ready' && item.messages >= 2,
      );
      final sample = database.transcript(
        revision.id,
        limit: _minimum(500, revision.messages),
      );
      final threadCounts = <String, int>{};
      for (final message in sample) {
        threadCounts.update(
          message.threadId,
          (count) => count + 1,
          ifAbsent: () => 1,
        );
      }
      final hit = sample.firstWhere(
        (message) => (threadCounts[message.threadId] ?? 0) >= 2,
      );
      final created = database.createEvidenceBlock(
        revisionId: revision.id,
        hitOrdinal: hit.ordinal,
        title: 'Flutter real-EVW round trip',
      );
      expect(created.messageIds.length, greaterThanOrEqualTo(2));
      expect(created.coreMessageId, hit.id);
      final updated = database.updateEvidenceMetadata(
        revisionId: revision.id,
        evidenceBlockId: created.id,
        title: 'Flutter real-EVW round trip complete',
        summary: 'Created by the opt-in real schema integration test.',
      );
      expect(updated.title, endsWith('complete'));
      database.checkpoint();
    });

    testWidgets('real v15 EVW deep transcript jump remains bounded', (
      tester,
    ) async {
      final database = EvwDatabase.open(realEvwPath);
      addTearDown(database.close);
      final revision = database.revisions().firstWhere(
        (item) => item.status == 'ready' && item.messages > 10000,
      );
      final controller = TranscriptDocumentController(
        database: database,
        revision: revision,
      )..reload();
      addTearDown(controller.dispose);
      final key = GlobalKey<VirtualTranscriptViewState>();
      final timer = Stopwatch()..start();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 1200,
              height: 700,
              child: VirtualTranscriptView(key: key, controller: controller),
            ),
          ),
        ),
      );
      await tester.pump();
      final firstPaint = timer.elapsed;
      expect(key.currentState!.cachedMessageCount, lessThan(800));
      expect(
        key.currentState!.scrollToOrdinal(revision.messages - 100),
        isTrue,
      );
      await tester.pump();
      await tester.pump();
      final deepJump = timer.elapsed - firstPaint;
      expect(
        key.currentState!.visibleEnd,
        greaterThanOrEqualTo(revision.messages - 100),
      );
      expect(key.currentState!.cachedMessageCount, lessThan(800));
      expect(firstPaint, lessThan(const Duration(seconds: 3)));
      expect(deepJump, lessThan(const Duration(seconds: 3)));
    });
  }
}

int _minimum(int left, int right) => left < right ? left : right;

class _Fixture {
  _Fixture({required this.messageCount, this.interleaveThreads = false}) {
    raw.execute('PRAGMA foreign_keys=ON');
    raw.execute('''
      CREATE TABLE workspace_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE dataset(
        dataset_id INTEGER PRIMARY KEY,name TEXT,created_at TEXT,
        schema_version INTEGER,content_revision INTEGER
      );
      CREATE TABLE source_thread(
        source_thread_id TEXT PRIMARY KEY,dataset_id INTEGER,
        display_title TEXT,source_platform TEXT,platform_thread_id TEXT,
        start_ts TEXT,end_ts TEXT
      );
      CREATE TABLE message(
        message_id TEXT PRIMARY KEY,dataset_id INTEGER,source_thread_id TEXT,
        timestamp TEXT,sender_display TEXT,body TEXT,
        body_normalized TEXT NOT NULL DEFAULT '',
        embedding_input_hash TEXT NOT NULL DEFAULT '',
        sort_index INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE category(
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,dataset_id INTEGER,
        name TEXT,created_at TEXT,updated_at TEXT
      );
      CREATE TABLE working_corpus(
        working_corpus_id INTEGER PRIMARY KEY,dataset_id INTEGER,name TEXT,
        current_revision_id INTEGER
      );
      CREATE TABLE working_corpus_revision(
        working_corpus_revision_id INTEGER PRIMARY KEY,
        working_corpus_id INTEGER,revision_number INTEGER,status TEXT,
        message_count INTEGER,estimated_tokens INTEGER,scope_hash TEXT
      );
      CREATE TABLE working_corpus_revision_message(
        working_corpus_revision_id INTEGER,message_id TEXT,
        source_thread_id TEXT,ordinal INTEGER,
        PRIMARY KEY(working_corpus_revision_id,message_id)
      );
      CREATE TABLE working_corpus_revision_index(
        working_corpus_revision_id INTEGER,index_generation INTEGER,
        status TEXT,fts_status TEXT,message_embedding_status TEXT,
        chunk_embedding_status TEXT,
        PRIMARY KEY(working_corpus_revision_id,index_generation)
      );
      CREATE TABLE evidence_block(
        evidence_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id INTEGER,category_id INTEGER,source_thread_id TEXT,
        title TEXT,summary TEXT,context_start_message_id TEXT,
        relevant_start_message_id TEXT,core_message_id TEXT,
        relevant_end_message_id TEXT,context_end_message_id TEXT,
        origin_kind TEXT,origin_working_corpus_revision_id INTEGER,
        origin_scope_hash TEXT,created_by TEXT,created_at TEXT,updated_at TEXT
      );
      CREATE TABLE evidence_block_message(
        evidence_block_id INTEGER,message_id TEXT,ordinal INTEGER,section TEXT,
        message_content_hash TEXT,
        PRIMARY KEY(evidence_block_id,message_id),
        FOREIGN KEY(evidence_block_id) REFERENCES evidence_block(evidence_block_id)
          ON DELETE CASCADE
      );
      CREATE TABLE evidence_block_highlight(
        evidence_block_id INTEGER,message_id TEXT,
        PRIMARY KEY(evidence_block_id,message_id),
        FOREIGN KEY(evidence_block_id,message_id)
          REFERENCES evidence_block_message(evidence_block_id,message_id)
          ON DELETE CASCADE
      );
      CREATE TABLE working_corpus_revision_evidence_block(
        working_corpus_revision_id INTEGER,evidence_block_id INTEGER,
        inherited_from_revision_id INTEGER,associated_at TEXT,
        PRIMARY KEY(working_corpus_revision_id,evidence_block_id)
      );
      CREATE VIRTUAL TABLE message_fts USING fts5(
        message_id UNINDEXED,working_corpus_revision_id UNINDEXED,
        index_generation UNINDEXED,source_thread_id UNINDEXED,
        body,body_normalized,sender_display
      );
    ''');
    raw.execute(
      "INSERT INTO workspace_state VALUES ('updated_at','2026-01-01T00:00:00Z')",
    );
    raw.execute("INSERT INTO workspace_state VALUES ('workspace_open','0')");
    raw.execute(
      "INSERT INTO dataset VALUES (1,'Test','2026-01-01T00:00:00Z',15,1)",
    );
    raw.execute(
      "INSERT INTO category(dataset_id,name,created_at,updated_at) VALUES (1,'Uncategorized','now','now')",
    );
    for (final thread in ['thread-a', 'thread-b']) {
      raw.execute('INSERT INTO source_thread VALUES (?,?,?,?,?,?,?)', [
        thread,
        1,
        thread == 'thread-a' ? 'Conversation A' : 'Conversation B',
        'test',
        thread,
        '2026-01-01T00:00:00Z',
        '2026-01-02T00:00:00Z',
      ]);
    }
    raw.execute("INSERT INTO working_corpus VALUES (1,1,'Corpus',1)");
    raw.execute(
      "INSERT INTO working_corpus_revision VALUES (1,1,1,'ready',?,?,?)",
      [messageCount, messageCount * 4, 'a' * 64],
    );
    raw.execute(
      "INSERT INTO working_corpus_revision_index VALUES (1,1,'ready','ready','ready','missing')",
    );
    for (var ordinal = 0; ordinal < messageCount; ordinal++) {
      final thread = interleaveThreads && ordinal.isOdd
          ? 'thread-b'
          : 'thread-a';
      final id = 'm${ordinal.toString().padLeft(3, '0')}';
      raw.execute(
        'INSERT INTO message(message_id,dataset_id,source_thread_id,timestamp,sender_display,body) VALUES (?,?,?,?,?,?)',
        [
          id,
          1,
          thread,
          '2026-01-01T00:${(ordinal % 60).toString().padLeft(2, '0')}:00Z',
          ordinal.isEven ? 'Alice' : 'Bob',
          ordinal % 11 == 0
              ? 'Long message ${'body ' * 50}$ordinal'
              : 'Message body $ordinal',
        ],
      );
      raw.execute(
        'INSERT INTO working_corpus_revision_message VALUES (1,?,?,?)',
        [id, thread, ordinal],
      );
      raw.execute('INSERT INTO message_fts VALUES (?,?,?,?,?,?,?)', [
        id,
        1,
        1,
        thread,
        ordinal % 11 == 0 ? 'Long message' : 'Message body',
        '',
        ordinal.isEven ? 'Alice' : 'Bob',
      ]);
    }
    database = EvwDatabase.forTesting(raw);
    revision = RevisionSummary(
      id: 1,
      corpusId: 1,
      datasetId: 1,
      number: 1,
      status: 'ready',
      messages: messageCount,
      tokens: messageCount * 4,
      scopeHash: 'a' * 64,
      generation: 1,
      messageEmbeddingStatus: 'ready',
      chunkEmbeddingStatus: 'ready',
    );
  }

  final int messageCount;
  final bool interleaveThreads;
  final Database raw = sqlite3.openInMemory();
  late final EvwDatabase database;
  late final RevisionSummary revision;

  TranscriptMessage message(int ordinal) =>
      database.messageAtOrdinal(revision.id, ordinal)!;

  void close() => database.close();
}
