import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:sqlite3/sqlite3.dart';

import 'evw_models.dart';

class EvwDatabase {
  EvwDatabase._(this.path, this.db, this._lockFile);

  final String path;
  final Database db;
  final RandomAccessFile? _lockFile;
  bool _closed = false;

  static EvwDatabase open(String path) {
    final file = File(path).absolute;
    if (!file.existsSync()) {
      throw StateError('EVW file does not exist: ${file.path}');
    }

    RandomAccessFile? lockFile;
    Database? db;
    try {
      final lock = File('${file.path}.lock');
      lockFile = lock.openSync(mode: FileMode.append);
      if (lockFile.lengthSync() == 0) {
        lockFile.writeByteSync(0);
        lockFile.flushSync();
      }
      try {
        lockFile.lockSync(FileLock.exclusive, 0, 1);
      } on FileSystemException catch (error) {
        throw StateError('Workspace is already open: ${file.path} ($error)');
      }

      db = sqlite3.open(file.path, mode: OpenMode.readWrite);
      db.execute('PRAGMA foreign_keys=ON');
      db.execute('PRAGMA journal_mode=WAL');
      db.execute('PRAGMA synchronous=FULL');
      db.execute('PRAGMA busy_timeout=5000');
      db.execute('PRAGMA wal_autocheckpoint=1000');

      final quick = db.select('PRAGMA quick_check').first.columnAt(0);
      if (quick != 'ok') throw StateError('EVW quick_check failed: $quick');
      final version = db
          .select('SELECT version FROM schema_version LIMIT 1')
          .first
          .columnAt(0);
      if (version != 15) {
        throw StateError(
          'Unsupported EVW schema version: $version; expected 15',
        );
      }
      _validateShape(db);
      final foreign = db.select('PRAGMA foreign_key_check');
      if (foreign.isNotEmpty) {
        throw StateError(
          'EVW foreign_key_check found ${foreign.length} violation(s)',
        );
      }

      final openRow = db.select(
        "SELECT value FROM workspace_state WHERE key='workspace_open'",
      );
      final previousCloseWasUnclean =
          openRow.isNotEmpty && openRow.first.columnAt(0) == '1';
      db.select('PRAGMA wal_checkpoint(PASSIVE)');
      final truncated = db.select('PRAGMA wal_checkpoint(TRUNCATE)').first;
      if ((truncated.columnAt(0) as int) != 0) {
        throw StateError(
          'WAL checkpoint was busy while opening ${file.path}: '
          '${truncated.columnAt(0)}, ${truncated.columnAt(1)}, ${truncated.columnAt(2)}',
        );
      }
      db.execute('BEGIN IMMEDIATE');
      db.execute(
        "UPDATE workspace_state SET value='1' WHERE key='workspace_open'",
      );
      db.execute('COMMIT');
      if (previousCloseWasUnclean) {
        stderr.writeln(
          'Recovered committed WAL after an unclean EVW close: ${file.path}',
        );
      }
      return EvwDatabase._(file.path, db, lockFile);
    } catch (_) {
      db?.dispose();
      if (lockFile != null) {
        try {
          lockFile.unlockSync(0, 1);
        } catch (_) {}
        lockFile.closeSync();
      }
      rethrow;
    }
  }

  static EvwDatabase forTesting(Database db) =>
      EvwDatabase._(':memory:', db, null);

  static void _validateShape(Database db) {
    _requireTables(db, [
      'schema_version',
      'workspace_state',
      'dataset',
      'source_thread',
      'message',
      'category',
      'working_corpus',
      'working_corpus_revision',
      'working_corpus_revision_message',
      'working_corpus_revision_index',
      'evidence_block',
      'evidence_block_message',
      'evidence_block_highlight',
      'working_corpus_revision_evidence_block',
      'message_fts',
      'embedding_artifact',
      'embedding_cache_state',
      'conversation',
      'conversation_turn',
      'conversation_citation',
      'printable_artifact_group',
      'printable_artifact',
      'printable_artifact_evidence_block',
    ]);
    _requireColumns(db, 'working_corpus', [
      'working_corpus_id',
      'dataset_id',
      'name',
      'current_revision_id',
    ]);
    _requireColumns(db, 'working_corpus_revision', [
      'working_corpus_revision_id',
      'working_corpus_id',
      'revision_number',
      'status',
      'message_count',
      'estimated_tokens',
      'scope_hash',
    ]);
    _requireColumns(db, 'working_corpus_revision_index', [
      'working_corpus_revision_id',
      'index_generation',
      'status',
      'fts_status',
      'message_embedding_status',
      'chunk_embedding_status',
    ]);
    _requireColumns(db, 'working_corpus_revision_message', [
      'working_corpus_revision_id',
      'message_id',
      'source_thread_id',
      'ordinal',
      'token_count',
      'embedding_input_hash',
    ]);
    _requireColumns(db, 'message', [
      'message_id',
      'source_thread_id',
      'timestamp',
      'sender_display',
      'body',
      'body_normalized',
      'embedding_input_hash',
      'sort_index',
    ]);
    _requireColumns(db, 'evidence_block', [
      'evidence_block_id',
      'dataset_id',
      'category_id',
      'source_thread_id',
      'title',
      'summary',
      'context_start_message_id',
      'relevant_start_message_id',
      'core_message_id',
      'relevant_end_message_id',
      'context_end_message_id',
      'origin_kind',
      'origin_working_corpus_revision_id',
      'origin_scope_hash',
    ]);
    _requireColumns(db, 'evidence_block_message', [
      'evidence_block_id',
      'message_id',
      'ordinal',
      'section',
      'message_content_hash',
    ]);
    _requireColumns(db, 'working_corpus_revision_evidence_block', [
      'working_corpus_revision_id',
      'evidence_block_id',
      'inherited_from_revision_id',
    ]);
    _requireColumns(db, 'message_fts', [
      'message_id',
      'working_corpus_revision_id',
      'index_generation',
      'source_thread_id',
      'body',
      'body_normalized',
      'sender_display',
    ]);
    _requireColumns(db, 'embedding_artifact', [
      'input_hash',
      'dimensions',
      'vector',
    ]);
    _requireColumns(db, 'embedding_cache_state', [
      'cache_id',
      'dimensions',
      'normalization',
    ]);
    _requireColumns(db, 'conversation', [
      'conversation_id',
      'dataset_id',
      'working_corpus_id',
      'working_corpus_revision_id',
      'index_generation',
      'scope_hash',
      'created_at',
      'status',
    ]);
    _requireColumns(db, 'conversation_turn', [
      'conversation_turn_id',
      'conversation_id',
      'working_corpus_id',
      'working_corpus_revision_id',
      'index_generation',
      'scope_hash',
      'user_prompt',
      'presented_answer',
      'mode',
      'status',
      'created_at',
    ]);
    _requireColumns(db, 'conversation_citation', [
      'conversation_citation_id',
      'conversation_turn_id',
      'message_id',
      'citation_type',
    ]);
    _requireColumns(db, 'printable_artifact_group', [
      'printable_artifact_group_id',
      'dataset_id',
      'name',
      'sort_order',
    ]);
    _requireColumns(db, 'printable_artifact', [
      'printable_artifact_id',
      'dataset_id',
      'group_id',
      'title',
      'exhibit_number',
      'case_number',
      'sort_order',
    ]);
    _requireColumns(db, 'printable_artifact_evidence_block', [
      'printable_artifact_evidence_block_id',
      'printable_artifact_id',
      'evidence_block_id',
      'sort_order',
    ]);
  }

  static void _requireTables(Database db, List<String> names) {
    for (final name in names) {
      final count =
          db
                  .select(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                    [name],
                  )
                  .first
                  .columnAt(0)
              as int;
      if (count != 1) throw StateError('Required v15 table is missing: $name');
    }
  }

  static void _requireColumns(
    Database db,
    String table,
    List<String> required,
  ) {
    final actual = db
        .select('PRAGMA table_info("$table")')
        .map((row) => row['name'] as String)
        .toSet();
    final missing = required.where((name) => !actual.contains(name)).toList();
    if (missing.isNotEmpty) {
      throw StateError(
        'Required v15 columns are missing from $table: ${missing.join(", ")}',
      );
    }
  }

  List<CorpusSummary> corpora() => db
      .select(
        'SELECT working_corpus_id,name,current_revision_id FROM working_corpus ORDER BY name,working_corpus_id',
      )
      .map(
        (row) => CorpusSummary(
          row['working_corpus_id'] as int,
          row['name'] as String,
          row['current_revision_id'] as int?,
        ),
      )
      .toList();

  List<RevisionSummary> revisions() => db
      .select('''SELECT r.working_corpus_revision_id,r.working_corpus_id,
          wc.dataset_id,r.revision_number,r.status,r.message_count,
          r.estimated_tokens,r.scope_hash,
          (SELECT MAX(index_generation)
             FROM working_corpus_revision_index i
            WHERE i.working_corpus_revision_id=r.working_corpus_revision_id) AS generation,
          (SELECT i.message_embedding_status
             FROM working_corpus_revision_index i
            WHERE i.working_corpus_revision_id=r.working_corpus_revision_id
            ORDER BY i.index_generation DESC LIMIT 1) AS message_embedding_status,
          (SELECT i.fts_status
             FROM working_corpus_revision_index i
            WHERE i.working_corpus_revision_id=r.working_corpus_revision_id
            ORDER BY i.index_generation DESC LIMIT 1) AS fts_status,
          (SELECT i.chunk_embedding_status
             FROM working_corpus_revision_index i
            WHERE i.working_corpus_revision_id=r.working_corpus_revision_id
            ORDER BY i.index_generation DESC LIMIT 1) AS chunk_embedding_status
        FROM working_corpus_revision r
        JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id
        ORDER BY r.working_corpus_id,r.revision_number''')
      .map(
        (row) => RevisionSummary(
          id: row['working_corpus_revision_id'] as int,
          corpusId: row['working_corpus_id'] as int,
          datasetId: row['dataset_id'] as int,
          number: row['revision_number'] as int,
          status: row['status'] as String,
          messages: row['message_count'] as int,
          tokens: row['estimated_tokens'] as int,
          scopeHash: row['scope_hash'] as String,
          generation: row['generation'] as int?,
          ftsStatus: row['fts_status'] as String?,
          messageEmbeddingStatus: row['message_embedding_status'] as String?,
          chunkEmbeddingStatus: row['chunk_embedding_status'] as String?,
        ),
      )
      .toList();

  List<TranscriptMessage> transcript(
    int revisionId, {
    int limit = 100,
    int offset = 0,
  }) => db
      .select(
        '''SELECT m.message_id,m.source_thread_id,t.display_title,
          w.ordinal,m.timestamp,m.sender_display,m.body
        FROM working_corpus_revision_message w
        JOIN message m ON m.message_id=w.message_id
        JOIN source_thread t ON t.source_thread_id=m.source_thread_id
        WHERE w.working_corpus_revision_id=?
        ORDER BY w.ordinal LIMIT ? OFFSET ?''',
        [revisionId, limit, offset],
      )
      .map(_messageFromRow)
      .toList();

  TranscriptMessage? messageAtOrdinal(int revisionId, int ordinal) {
    final rows = transcript(revisionId, limit: 1, offset: ordinal);
    return rows.isEmpty ? null : rows.first;
  }

  TranscriptMessage? coreMessageForRange(
    int revisionId,
    String startMessageId,
    String endMessageId,
  ) {
    final endpoints = db.select(
      '''SELECT message_id,source_thread_id,ordinal
         FROM working_corpus_revision_message
         WHERE working_corpus_revision_id=? AND message_id IN (?,?)
         ORDER BY ordinal''',
      [revisionId, startMessageId, endMessageId],
    );
    final start = endpoints
        .where((row) => row['message_id'] == startMessageId)
        .firstOrNull;
    final end = endpoints
        .where((row) => row['message_id'] == endMessageId)
        .firstOrNull;
    if (start == null ||
        end == null ||
        start['source_thread_id'] != end['source_thread_id'] ||
        (start['ordinal'] as int) > (end['ordinal'] as int)) {
      return null;
    }
    final rows = db.select(
      '''SELECT m.message_id,m.source_thread_id,t.display_title,
                w.ordinal,m.timestamp,m.sender_display,m.body
         FROM working_corpus_revision_message w
         JOIN message m ON m.message_id=w.message_id
         JOIN source_thread t ON t.source_thread_id=m.source_thread_id
         WHERE w.working_corpus_revision_id=? AND w.source_thread_id=?
           AND w.ordinal>=? AND w.ordinal<=?
         ORDER BY w.ordinal''',
      [revisionId, start['source_thread_id'], start['ordinal'], end['ordinal']],
    );
    if (rows.isEmpty) return null;
    return _messageFromRow(rows[(rows.length - 1) ~/ 2]);
  }

  SearchPage ftsSearch(
    int revisionId,
    String query, {
    required int indexGeneration,
    int limit = 100,
    int offset = 0,
  }) {
    if (limit < 1 || offset < 0) {
      throw ArgumentError(
        'FTS pagination must use a positive limit and nonnegative offset',
      );
    }
    final terms = RegExp(r"[\p{L}\p{N}_']+", unicode: true)
        .allMatches(query.trim())
        .map((match) => match.group(0)!)
        .where((term) => term.isNotEmpty)
        .toList();
    if (terms.isEmpty) {
      throw ArgumentError('Search query contains no searchable terms');
    }
    _requireReadyFtsScope(revisionId, indexGeneration);
    final ftsQuery = terms
        .map((term) => '"${term.replaceAll('"', '""')}"')
        .join(' AND ');
    const from = '''
      FROM message_fts f
      JOIN message m ON m.message_id=f.message_id
      JOIN source_thread t ON t.source_thread_id=m.source_thread_id
      JOIN working_corpus_revision_message w
        ON w.working_corpus_revision_id=? AND w.message_id=m.message_id
      WHERE f.working_corpus_revision_id=?
        AND f.index_generation=?
        AND message_fts MATCH ?
    ''';
    final params = [revisionId, revisionId, indexGeneration, ftsQuery];
    final total =
        (db.select('SELECT COUNT(*) $from', params).first.columnAt(0) as int);
    final rows = db.select(
      '''SELECT f.message_id,f.source_thread_id,t.display_title,m.timestamp,
                m.sender_display,m.body,w.ordinal,bm25(message_fts) AS rank
           $from
          ORDER BY rank,m.timestamp,m.sort_index,m.message_id
          LIMIT ? OFFSET ?''',
      [...params, limit, offset],
    );
    final hits = rows
        .map(
          (row) => SearchHit(
            messageId: row['message_id'] as String,
            threadId: row['source_thread_id'] as String,
            threadTitle: row['display_title'] as String,
            ordinal: row['ordinal'] as int,
            timestamp: row['timestamp'] as String,
            sender: row['sender_display'] as String,
            body: row['body'] as String,
            matchType: 'exact',
            rank: (row['rank'] as num).toDouble(),
          ),
        )
        .toList();
    final nextOffset = offset + hits.length;
    return SearchPage(
      hits: hits,
      totalCount: total,
      hasMore: nextOffset < total,
      nextOffset: nextOffset < total ? nextOffset : null,
    );
  }

  void _requireReadyFtsScope(int revisionId, int indexGeneration) {
    final rows = db.select(
      '''SELECT r.status,i.status AS index_status,i.fts_status
           FROM working_corpus_revision r
           JOIN working_corpus_revision_index i
             ON i.working_corpus_revision_id=r.working_corpus_revision_id
            AND i.index_generation=?
          WHERE r.working_corpus_revision_id=?''',
      [indexGeneration, revisionId],
    );
    if (rows.isEmpty ||
        rows.first['status'] != 'ready' ||
        rows.first['index_status'] != 'ready' ||
        rows.first['fts_status'] != 'ready') {
      throw StateError(
        'Working corpus revision $revisionId and index generation $indexGeneration are not ready for FTS5 search',
      );
    }
  }

  EmbeddingGeometry embeddingGeometry({
    required int revisionId,
    required int indexGeneration,
  }) {
    _requireReadyEmbeddingScope(revisionId, indexGeneration);
    final row = db
        .select(
          'SELECT dimensions,normalization FROM embedding_cache_state WHERE cache_id=1',
        )
        .first;
    return EmbeddingGeometry(
      dimensions: row['dimensions'] as int,
      normalization: row['normalization'] as String,
    );
  }

  List<SearchHit> vectorSearch({
    required int revisionId,
    required int indexGeneration,
    required List<double> queryVector,
    required int topK,
  }) {
    if (topK < 1 || topK > 1000) {
      throw ArgumentError('Top results must be between 1 and 1000');
    }
    final geometry = embeddingGeometry(
      revisionId: revisionId,
      indexGeneration: indexGeneration,
    );
    if (queryVector.length != geometry.dimensions ||
        queryVector.any((value) => !value.isFinite)) {
      throw StateError('EMBEDDING_CACHE_GEOMETRY_MISMATCH');
    }
    final bytes = ByteData(queryVector.length * 4);
    for (var index = 0; index < queryVector.length; index++) {
      bytes.setFloat32(index * 4, queryVector[index], Endian.little);
    }
    final rows = db.select(
      '''SELECT m.message_id,m.source_thread_id,t.display_title,m.timestamp,
                m.sender_display,m.body,w.ordinal,
                vec_distance_L2(e.vector, ?) AS distance
           FROM working_corpus_revision_message w
           JOIN message m ON m.message_id=w.message_id
           JOIN source_thread t ON t.source_thread_id=m.source_thread_id
           JOIN embedding_artifact e ON e.input_hash=w.embedding_input_hash
          WHERE w.working_corpus_revision_id=?
          ORDER BY distance,m.timestamp,m.sort_index,m.message_id
          LIMIT ?''',
      [bytes.buffer.asUint8List(), revisionId, topK],
    );
    return rows
        .asMap()
        .entries
        .map(
          (entry) => SearchHit(
            messageId: entry.value['message_id'] as String,
            threadId: entry.value['source_thread_id'] as String,
            threadTitle: entry.value['display_title'] as String,
            ordinal: entry.value['ordinal'] as int,
            timestamp: entry.value['timestamp'] as String,
            sender: entry.value['sender_display'] as String,
            body: entry.value['body'] as String,
            matchType: 'embedding',
            rank: (entry.key + 1).toDouble(),
            distance: (entry.value['distance'] as num).toDouble(),
          ),
        )
        .toList();
  }

  void _requireReadyEmbeddingScope(int revisionId, int indexGeneration) {
    final rows = db.select(
      '''SELECT r.status,i.status AS index_status,i.message_embedding_status
           FROM working_corpus_revision r
           JOIN working_corpus_revision_index i
             ON i.working_corpus_revision_id=r.working_corpus_revision_id
            AND i.index_generation=?
          WHERE r.working_corpus_revision_id=?''',
      [indexGeneration, revisionId],
    );
    final cache = db.select(
      'SELECT dimensions FROM embedding_cache_state WHERE cache_id=1',
    );
    if (rows.isEmpty ||
        rows.first['status'] != 'ready' ||
        rows.first['index_status'] != 'ready' ||
        rows.first['message_embedding_status'] != 'ready' ||
        cache.isEmpty) {
      throw StateError(
        'The selected revision does not have a ready local message embedding index',
      );
    }
  }

  void persistConversation({
    required int revisionId,
    required int indexGeneration,
    required String scopeHash,
    required String prompt,
    required String presentedAnswer,
    required String mode,
    required Map<String, dynamic> result,
  }) {
    _readyScope(revisionId);
    final scopeRows = db.select(
      '''SELECT wc.working_corpus_id,wc.dataset_id,r.scope_hash
           FROM working_corpus_revision r
           JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id
          WHERE r.working_corpus_revision_id=?''',
      [revisionId],
    );
    if (scopeRows.isEmpty ||
        scopeRows.first['scope_hash'] != scopeHash ||
        scopeRows.first['working_corpus_id'] == null) {
      throw StateError(
        'Selected working-corpus scope changed before persistence',
      );
    }
    final workingCorpusId = scopeRows.first['working_corpus_id'] as int;
    final datasetId = scopeRows.first['dataset_id'] as int;
    final status = result['completion_status'] as String;
    final now = DateTime.now().toUtc().toIso8601String();
    _write(() {
      db.execute(
        '''INSERT INTO conversation(
          dataset_id,working_corpus_id,working_corpus_revision_id,
          index_generation,scope_hash,created_at,status)
          VALUES (?,?,?,?,?,?,?)''',
        [
          datasetId,
          workingCorpusId,
          revisionId,
          indexGeneration,
          scopeHash,
          now,
          status,
        ],
      );
      final conversationId = db.lastInsertRowId;
      db.execute(
        '''INSERT INTO conversation_turn(
          conversation_id,working_corpus_id,working_corpus_revision_id,
          index_generation,scope_hash,user_prompt,presented_answer,mode,
          status,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?)''',
        [
          conversationId,
          workingCorpusId,
          revisionId,
          indexGeneration,
          scopeHash,
          prompt,
          presentedAnswer,
          mode,
          status,
          now,
        ],
      );
      final turnId = db.lastInsertRowId;
      final cited = <String>{};
      final ledger = result['evidence_ledger'];
      if (ledger is List) {
        for (final item in ledger) {
          if (item is! Map) continue;
          for (final key in ['start_message_id', 'end_message_id']) {
            final messageId = item[key];
            if (messageId is! String || !cited.add(messageId)) continue;
            final member = db.select(
              '''SELECT 1 FROM working_corpus_revision_message
                  WHERE working_corpus_revision_id=? AND message_id=?''',
              [revisionId, messageId],
            );
            if (member.isEmpty) {
              cited.remove(messageId);
              continue;
            }
            db.execute(
              'INSERT INTO conversation_citation(conversation_turn_id,message_id,citation_type) VALUES (?,?,?)',
              [
                turnId,
                messageId,
                key == 'start_message_id' ? 'range_start' : 'range_end',
              ],
            );
          }
        }
      }
      _touchWorkspace(now);
    });
  }

  int? ordinalForMessage(int revisionId, String messageId) {
    final rows = db.select(
      '''SELECT ordinal FROM working_corpus_revision_message
         WHERE working_corpus_revision_id=? AND message_id=?''',
      [revisionId, messageId],
    );
    return rows.isEmpty ? null : rows.first['ordinal'] as int;
  }

  TranscriptMessage? nearestMessageInThread(
    int revisionId,
    String sourceThreadId,
    int ordinal,
  ) {
    final before = db.select(
      '''SELECT m.message_id,m.source_thread_id,t.display_title,
          w.ordinal,m.timestamp,m.sender_display,m.body
         FROM working_corpus_revision_message w
         JOIN message m ON m.message_id=w.message_id
         JOIN source_thread t ON t.source_thread_id=m.source_thread_id
         WHERE w.working_corpus_revision_id=? AND w.source_thread_id=?
           AND w.ordinal<=?
         ORDER BY w.ordinal DESC LIMIT 1''',
      [revisionId, sourceThreadId, ordinal],
    );
    final after = db.select(
      '''SELECT m.message_id,m.source_thread_id,t.display_title,
          w.ordinal,m.timestamp,m.sender_display,m.body
         FROM working_corpus_revision_message w
         JOIN message m ON m.message_id=w.message_id
         JOIN source_thread t ON t.source_thread_id=m.source_thread_id
         WHERE w.working_corpus_revision_id=? AND w.source_thread_id=?
           AND w.ordinal>=?
         ORDER BY w.ordinal LIMIT 1''',
      [revisionId, sourceThreadId, ordinal],
    );
    if (before.isEmpty && after.isEmpty) return null;
    if (before.isEmpty) return _messageFromRow(after.first);
    if (after.isEmpty) return _messageFromRow(before.first);
    final left = _messageFromRow(before.first);
    final right = _messageFromRow(after.first);
    return ordinal - left.ordinal <= right.ordinal - ordinal ? left : right;
  }

  static TranscriptMessage _messageFromRow(Row row) => TranscriptMessage(
    id: row['message_id'] as String,
    threadId: row['source_thread_id'] as String,
    threadTitle: row['display_title'] as String,
    ordinal: row['ordinal'] as int,
    timestamp: row['timestamp'] as String,
    sender: row['sender_display'] as String,
    body: row['body'] as String,
  );

  List<EvidenceSummary> evidence(int? revisionId) {
    final rows = revisionId == null
        ? db.select(
            '''SELECT b.evidence_block_id,b.title,b.summary,b.origin_kind,
              b.origin_working_corpus_revision_id,b.origin_scope_hash,
              NULL AS inherited_from_revision_id,
              (SELECT COUNT(*) FROM evidence_block_message m
                WHERE m.evidence_block_id=b.evidence_block_id) AS message_count
            FROM evidence_block b ORDER BY b.evidence_block_id''',
          )
        : db.select(
            '''SELECT b.evidence_block_id,b.title,b.summary,b.origin_kind,
              b.origin_working_corpus_revision_id,b.origin_scope_hash,
              a.inherited_from_revision_id,
              (SELECT COUNT(*) FROM evidence_block_message m
                WHERE m.evidence_block_id=b.evidence_block_id) AS message_count
            FROM evidence_block b
            JOIN working_corpus_revision_evidence_block a
              ON a.evidence_block_id=b.evidence_block_id
            WHERE a.working_corpus_revision_id=?
            ORDER BY b.evidence_block_id''',
            [revisionId],
          );
    return rows
        .map(
          (row) => EvidenceSummary(
            id: row['evidence_block_id'] as int,
            title: row['title'] as String,
            summary: row['summary'] as String,
            originKind: row['origin_kind'] as String,
            originWorkingCorpusRevisionId:
                row['origin_working_corpus_revision_id'] as int?,
            originScopeHash: row['origin_scope_hash'] as String?,
            inheritedFromRevisionId: row['inherited_from_revision_id'] as int?,
            messageCount: row['message_count'] as int,
          ),
        )
        .toList();
  }

  List<EvidenceBlock> evidenceBlocks(int revisionId) {
    final rows = db.select(
      '''SELECT b.*,
          cs.ordinal AS context_start_ordinal,
          rs.ordinal AS relevant_start_ordinal,
          core.ordinal AS core_ordinal,
          re.ordinal AS relevant_end_ordinal,
          ce.ordinal AS context_end_ordinal
        FROM evidence_block b
        JOIN working_corpus_revision_evidence_block a
          ON a.evidence_block_id=b.evidence_block_id
        JOIN working_corpus_revision_message cs
          ON cs.working_corpus_revision_id=a.working_corpus_revision_id
         AND cs.message_id=b.context_start_message_id
        JOIN working_corpus_revision_message rs
          ON rs.working_corpus_revision_id=a.working_corpus_revision_id
         AND rs.message_id=b.relevant_start_message_id
        JOIN working_corpus_revision_message core
          ON core.working_corpus_revision_id=a.working_corpus_revision_id
         AND core.message_id=b.core_message_id
        JOIN working_corpus_revision_message re
          ON re.working_corpus_revision_id=a.working_corpus_revision_id
         AND re.message_id=b.relevant_end_message_id
        JOIN working_corpus_revision_message ce
          ON ce.working_corpus_revision_id=a.working_corpus_revision_id
         AND ce.message_id=b.context_end_message_id
        WHERE a.working_corpus_revision_id=?
        ORDER BY b.evidence_block_id''',
      [revisionId],
    );
    return rows.map((row) => _evidenceBlockFromRow(row, revisionId)).toList();
  }

  EvidenceBlock evidenceBlock(int revisionId, int evidenceBlockId) {
    final block = evidenceBlocks(
      revisionId,
    ).where((item) => item.id == evidenceBlockId).toList();
    if (block.length != 1) {
      throw StateError(
        'Evidence block $evidenceBlockId is not associated with revision $revisionId',
      );
    }
    return block.single;
  }

  EvidenceBlock _datasetEvidenceBlock(int datasetId, int evidenceBlockId) {
    final rows = db.select(
      '''SELECT b.*,
          cs.ordinal AS context_start_ordinal,
          rs.ordinal AS relevant_start_ordinal,
          core.ordinal AS core_ordinal,
          re.ordinal AS relevant_end_ordinal,
          ce.ordinal AS context_end_ordinal
        FROM evidence_block b
        JOIN evidence_block_message cs
          ON cs.evidence_block_id=b.evidence_block_id
         AND cs.message_id=b.context_start_message_id
        JOIN evidence_block_message rs
          ON rs.evidence_block_id=b.evidence_block_id
         AND rs.message_id=b.relevant_start_message_id
        JOIN evidence_block_message core
          ON core.evidence_block_id=b.evidence_block_id
         AND core.message_id=b.core_message_id
        JOIN evidence_block_message re
          ON re.evidence_block_id=b.evidence_block_id
         AND re.message_id=b.relevant_end_message_id
        JOIN evidence_block_message ce
          ON ce.evidence_block_id=b.evidence_block_id
         AND ce.message_id=b.context_end_message_id
        WHERE b.evidence_block_id=? AND b.dataset_id=?''',
      [evidenceBlockId, datasetId],
    );
    if (rows.length != 1) {
      throw StateError(
        'Evidence block $evidenceBlockId does not belong to dataset $datasetId',
      );
    }
    return _evidenceBlockFromRow(rows.single, 0);
  }

  EvidenceBlock _evidenceBlockFromRow(Row row, int revisionId) {
    final members = db.select(
      '''SELECT m.message_id,m.section,
          CASE WHEN h.message_id IS NULL THEN 0 ELSE 1 END AS highlighted
        FROM evidence_block_message m
        LEFT JOIN evidence_block_highlight h
          ON h.evidence_block_id=m.evidence_block_id
         AND h.message_id=m.message_id
        WHERE m.evidence_block_id=? ORDER BY m.ordinal''',
      [row['evidence_block_id']],
    );
    final messageIds = <String>[];
    final sections = <String, String>{};
    final highlights = <String>{};
    for (final member in members) {
      final messageId = member['message_id'] as String;
      messageIds.add(messageId);
      sections[messageId] = member['section'] as String;
      if (member['highlighted'] == 1) highlights.add(messageId);
    }
    if (messageIds.isEmpty) {
      throw StateError(
        'Evidence block ${row['evidence_block_id']} has no exact messages',
      );
    }
    return EvidenceBlock(
      id: row['evidence_block_id'] as int,
      datasetId: row['dataset_id'] as int,
      categoryId: row['category_id'] as int,
      sourceThreadId: row['source_thread_id'] as String,
      title: row['title'] as String,
      summary: row['summary'] as String,
      contextStartMessageId: row['context_start_message_id'] as String,
      relevantStartMessageId: row['relevant_start_message_id'] as String,
      coreMessageId: row['core_message_id'] as String,
      relevantEndMessageId: row['relevant_end_message_id'] as String,
      contextEndMessageId: row['context_end_message_id'] as String,
      contextStartOrdinal: row['context_start_ordinal'] as int,
      relevantStartOrdinal: row['relevant_start_ordinal'] as int,
      coreOrdinal: row['core_ordinal'] as int,
      relevantEndOrdinal: row['relevant_end_ordinal'] as int,
      contextEndOrdinal: row['context_end_ordinal'] as int,
      messageIds: messageIds,
      sections: sections,
      highlightedMessageIds: highlights,
    );
  }

  List<PrintableArtifactGroupSummary> printableArtifactGroups(int datasetId) =>
      db
          .select(
            '''SELECT printable_artifact_group_id,dataset_id,name,sort_order
               FROM printable_artifact_group
               WHERE dataset_id=?
               ORDER BY sort_order,printable_artifact_group_id''',
            [datasetId],
          )
          .map(
            (row) => PrintableArtifactGroupSummary(
              id: row['printable_artifact_group_id'] as int,
              datasetId: row['dataset_id'] as int,
              name: row['name'] as String,
              sortOrder: row['sort_order'] as int,
            ),
          )
          .toList();

  List<PrintableArtifactSummary> printableArtifacts(int groupId) => db
      .select(
        '''SELECT printable_artifact_id,dataset_id,group_id,title,
                  exhibit_number,case_number,sort_order
           FROM printable_artifact
           WHERE group_id=?
           ORDER BY sort_order,printable_artifact_id''',
        [groupId],
      )
      .map(_printableArtifactFromRow)
      .toList();

  PrintableArtifactGroupSummary ensureDefaultPrintableArtifactGroup(
    int datasetId,
  ) {
    final existing = printableArtifactGroups(datasetId);
    if (existing.isNotEmpty) return existing.first;
    late int groupId;
    _write(() {
      final now = DateTime.now().toUtc().toIso8601String();
      db.execute(
        '''INSERT INTO printable_artifact_group(
             dataset_id,name,sort_order,is_collapsed,created_at,updated_at)
           VALUES (?,?,0,0,?,?)''',
        [datasetId, 'Default', now, now],
      );
      groupId = db.lastInsertRowId;
      _touchWorkspace(now);
    });
    return printableArtifactGroups(
      datasetId,
    ).firstWhere((group) => group.id == groupId);
  }

  PrintableArtifactDocument createPrintableArtifactFromEvidence({
    required int revisionId,
    required int evidenceBlockId,
    int? groupId,
  }) {
    final scope = _readyScope(revisionId);
    final evidence = evidenceBlock(revisionId, evidenceBlockId);
    if (evidence.datasetId != scope.datasetId) {
      throw StateError('Evidence block belongs to a different dataset');
    }
    late int artifactId;
    _write(() {
      var selectedGroupId = groupId;
      if (selectedGroupId == null) {
        final groups = db.select(
          '''SELECT printable_artifact_group_id FROM printable_artifact_group
             WHERE dataset_id=? ORDER BY sort_order,printable_artifact_group_id''',
          [scope.datasetId],
        );
        if (groups.isEmpty) {
          final now = DateTime.now().toUtc().toIso8601String();
          db.execute(
            '''INSERT INTO printable_artifact_group(
                 dataset_id,name,sort_order,is_collapsed,created_at,updated_at)
               VALUES (?, 'Default', 0, 0, ?, ?)''',
            [scope.datasetId, now, now],
          );
          selectedGroupId = db.lastInsertRowId;
        } else {
          selectedGroupId = groups.first['printable_artifact_group_id'] as int;
        }
      }
      final groupRows = db.select(
        'SELECT dataset_id FROM printable_artifact_group WHERE printable_artifact_group_id=?',
        [selectedGroupId],
      );
      if (groupRows.isEmpty ||
          groupRows.first['dataset_id'] != scope.datasetId) {
        throw StateError(
          'Printable artifact group belongs to a different dataset',
        );
      }
      final maxRows = db.select(
        'SELECT COALESCE(MAX(sort_order),-1) AS max_order FROM printable_artifact WHERE group_id=?',
        [selectedGroupId],
      );
      final now = DateTime.now().toUtc().toIso8601String();
      db.execute(
        '''INSERT INTO printable_artifact(
             dataset_id,group_id,title,exhibit_number,case_number,sort_order,created_at,updated_at)
           VALUES (?,?,?,'','',?,?,?)''',
        [
          scope.datasetId,
          selectedGroupId,
          evidence.title,
          (maxRows.first['max_order'] as int) + 1,
          now,
          now,
        ],
      );
      artifactId = db.lastInsertRowId;
      db.execute(
        '''INSERT INTO printable_artifact_evidence_block(
             printable_artifact_id,evidence_block_id,sort_order,created_at)
           VALUES (?,?,0,?)''',
        [artifactId, evidenceBlockId, now],
      );
      _touchWorkspace(now);
    });
    return printableArtifactDocument(
      revisionId: revisionId,
      artifactId: artifactId,
    );
  }

  PrintableArtifactDocument appendPrintableEvidenceBlock({
    required int revisionId,
    required int artifactId,
    required int evidenceBlockId,
  }) {
    final scope = _readyScope(revisionId);
    final evidence = evidenceBlock(revisionId, evidenceBlockId);
    if (evidence.datasetId != scope.datasetId) {
      throw StateError('Evidence block belongs to a different dataset');
    }
    _write(() {
      final artifactRows = db.select(
        'SELECT dataset_id FROM printable_artifact WHERE printable_artifact_id=?',
        [artifactId],
      );
      if (artifactRows.isEmpty ||
          artifactRows.first['dataset_id'] != scope.datasetId) {
        throw StateError('Printable artifact belongs to a different dataset');
      }
      final duplicate = db.select(
        '''SELECT 1 FROM printable_artifact_evidence_block
           WHERE printable_artifact_id=? AND evidence_block_id=?''',
        [artifactId, evidenceBlockId],
      );
      if (duplicate.isNotEmpty) {
        throw StateError('Evidence block is already attached to this artifact');
      }
      final maxRows = db.select(
        '''SELECT COALESCE(MAX(sort_order),-1) AS max_order
           FROM printable_artifact_evidence_block WHERE printable_artifact_id=?''',
        [artifactId],
      );
      final now = DateTime.now().toUtc().toIso8601String();
      db.execute(
        '''INSERT INTO printable_artifact_evidence_block(
             printable_artifact_id,evidence_block_id,sort_order,created_at)
           VALUES (?,?,?,?)''',
        [
          artifactId,
          evidenceBlockId,
          (maxRows.first['max_order'] as int) + 1,
          now,
        ],
      );
      _touchWorkspace(now);
    });
    return printableArtifactDocument(
      revisionId: revisionId,
      artifactId: artifactId,
    );
  }

  PrintableArtifactSummary updatePrintableArtifactMetadata({
    required int datasetId,
    required int artifactId,
    required String title,
    required String exhibitNumber,
    required String caseNumber,
  }) {
    late PrintableArtifactSummary result;
    _write(() {
      final now = DateTime.now().toUtc().toIso8601String();
      db.execute(
        '''UPDATE printable_artifact
           SET title=?,exhibit_number=?,case_number=?,updated_at=?
           WHERE printable_artifact_id=? AND dataset_id=?''',
        [title, exhibitNumber, caseNumber, now, artifactId, datasetId],
      );
      final rows = db.select(
        '''SELECT printable_artifact_id,dataset_id,group_id,title,
                  exhibit_number,case_number,sort_order
           FROM printable_artifact WHERE printable_artifact_id=? AND dataset_id=?''',
        [artifactId, datasetId],
      );
      if (rows.length != 1)
        throw StateError(
          'Printable artifact does not exist in the selected dataset',
        );
      result = _printableArtifactFromRow(rows.first);
      _touchWorkspace(now);
    });
    return result;
  }

  void movePrintableArtifactBlock({
    required int datasetId,
    required int artifactId,
    required int joinId,
    required int delta,
  }) {
    if (delta != -1 && delta != 1)
      throw ArgumentError('Move delta must be -1 or 1');
    _write(() {
      final artifact = db.select(
        'SELECT dataset_id FROM printable_artifact WHERE printable_artifact_id=?',
        [artifactId],
      );
      if (artifact.isEmpty || artifact.first['dataset_id'] != datasetId) {
        throw StateError('Printable artifact belongs to a different dataset');
      }
      final rows = db.select(
        '''SELECT printable_artifact_evidence_block_id FROM printable_artifact_evidence_block
           WHERE printable_artifact_id=? ORDER BY sort_order,printable_artifact_evidence_block_id''',
        [artifactId],
      );
      final ids = rows
          .map((row) => row['printable_artifact_evidence_block_id'] as int)
          .toList();
      final index = ids.indexOf(joinId);
      final target = index + delta;
      if (index < 0 || target < 0 || target >= ids.length) return;
      final moved = ids.removeAt(index);
      ids.insert(target, moved);
      for (var order = 0; order < ids.length; order++) {
        db.execute(
          'UPDATE printable_artifact_evidence_block SET sort_order=? WHERE printable_artifact_evidence_block_id=? AND printable_artifact_id=?',
          [order, ids[order], artifactId],
        );
      }
      _touchWorkspace(DateTime.now().toUtc().toIso8601String());
    });
  }

  void removePrintableArtifactBlock({
    required int datasetId,
    required int artifactId,
    required int joinId,
  }) {
    _write(() {
      final artifact = db.select(
        'SELECT dataset_id FROM printable_artifact WHERE printable_artifact_id=?',
        [artifactId],
      );
      if (artifact.isEmpty || artifact.first['dataset_id'] != datasetId) {
        throw StateError('Printable artifact belongs to a different dataset');
      }
      final join = db.select(
        'SELECT 1 FROM printable_artifact_evidence_block WHERE printable_artifact_evidence_block_id=? AND printable_artifact_id=?',
        [joinId, artifactId],
      );
      if (join.isEmpty)
        throw StateError('Printable artifact block does not exist');
      db.execute(
        'DELETE FROM printable_artifact_evidence_block WHERE printable_artifact_evidence_block_id=? AND printable_artifact_id=?',
        [joinId, artifactId],
      );
      final rows = db.select(
        '''SELECT printable_artifact_evidence_block_id FROM printable_artifact_evidence_block
           WHERE printable_artifact_id=? ORDER BY sort_order,printable_artifact_evidence_block_id''',
        [artifactId],
      );
      for (var order = 0; order < rows.length; order++) {
        db.execute(
          'UPDATE printable_artifact_evidence_block SET sort_order=? WHERE printable_artifact_evidence_block_id=?',
          [order, rows[order]['printable_artifact_evidence_block_id']],
        );
      }
      _touchWorkspace(DateTime.now().toUtc().toIso8601String());
    });
  }

  PrintableArtifactDocument printableArtifactDocument({
    required int revisionId,
    required int artifactId,
  }) {
    final scope = _readyScope(revisionId);
    final artifactRows = db.select(
      '''SELECT printable_artifact_id,dataset_id,group_id,title,
                exhibit_number,case_number,sort_order
         FROM printable_artifact
         WHERE printable_artifact_id=? AND dataset_id=?''',
      [artifactId, scope.datasetId],
    );
    if (artifactRows.length != 1) {
      throw StateError(
        'Printable artifact does not exist in the selected dataset',
      );
    }
    final artifact = _printableArtifactFromRow(artifactRows.first);
    final groups = db.select(
      'SELECT name FROM printable_artifact_group WHERE printable_artifact_group_id=? AND dataset_id=?',
      [artifact.groupId, scope.datasetId],
    );
    if (groups.length != 1)
      throw StateError('Printable artifact group is invalid');
    final joins = db.select(
      '''SELECT printable_artifact_evidence_block_id,evidence_block_id,sort_order
         FROM printable_artifact_evidence_block
         WHERE printable_artifact_id=?
         ORDER BY sort_order,printable_artifact_evidence_block_id''',
      [artifactId],
    );
    final blocks = <PrintableArtifactBlock>[];
    for (var index = 0; index < joins.length; index++) {
      final evidence = _datasetEvidenceBlock(
        scope.datasetId,
        joins[index]['evidence_block_id'] as int,
      );
      final rows = db.select(
        '''SELECT m.message_id,m.source_thread_id,t.display_title,
                  ebm.ordinal,m.timestamp,m.sender_display,m.body
           FROM evidence_block_message ebm
           JOIN message m ON m.message_id=ebm.message_id
           JOIN source_thread t ON t.source_thread_id=m.source_thread_id
           WHERE ebm.evidence_block_id=? ORDER BY ebm.ordinal''',
        [evidence.id],
      );
      blocks.add(
        PrintableArtifactBlock(
          joinId: joins[index]['printable_artifact_evidence_block_id'] as int,
          artifactId: artifactId,
          sortOrder: joins[index]['sort_order'] as int,
          label: 'Block ${index + 1}',
          evidence: evidence,
          messages: rows.map(_messageFromRow).toList(),
        ),
      );
    }
    return PrintableArtifactDocument(
      artifact: artifact,
      groupName: groups.first['name'] as String,
      blocks: blocks,
    );
  }

  PrintableArtifactSummary _printableArtifactFromRow(Row row) =>
      PrintableArtifactSummary(
        id: row['printable_artifact_id'] as int,
        datasetId: row['dataset_id'] as int,
        groupId: row['group_id'] as int,
        title: row['title'] as String,
        exhibitNumber: row['exhibit_number'] as String,
        caseNumber: row['case_number'] as String,
        sortOrder: row['sort_order'] as int,
      );

  List<CategorySummary> categories(int datasetId) => db
      .select(
        'SELECT category_id,name FROM category WHERE dataset_id=? ORDER BY name COLLATE NOCASE,category_id',
        [datasetId],
      )
      .map(
        (row) =>
            CategorySummary(row['category_id'] as int, row['name'] as String),
      )
      .toList();

  EvidenceBlock createEvidenceBlock({
    required int revisionId,
    required int hitOrdinal,
    String? title,
    String summary = '',
    String createdBy = 'transcript_editor',
  }) {
    final scope = _readyScope(revisionId);
    final hit = messageAtOrdinal(revisionId, hitOrdinal);
    if (hit == null) {
      throw StateError('No message exists at corpus ordinal $hitOrdinal');
    }
    final before = db.select(
      '''SELECT w.ordinal,m.message_id
         FROM working_corpus_revision_message w
         JOIN message m ON m.message_id=w.message_id
         WHERE w.working_corpus_revision_id=? AND w.source_thread_id=?
           AND w.ordinal<=?
         ORDER BY w.ordinal DESC LIMIT 4''',
      [revisionId, hit.threadId, hitOrdinal],
    );
    final after = db.select(
      '''SELECT w.ordinal,m.message_id
         FROM working_corpus_revision_message w
         JOIN message m ON m.message_id=w.message_id
         WHERE w.working_corpus_revision_id=? AND w.source_thread_id=?
           AND w.ordinal>=?
         ORDER BY w.ordinal LIMIT 4''',
      [revisionId, hit.threadId, hitOrdinal],
    );
    final context = <int, String>{};
    for (final row in [...before, ...after]) {
      context[row['ordinal'] as int] = row['message_id'] as String;
    }
    final ordered = context.entries.toList()
      ..sort((left, right) => left.key.compareTo(right.key));
    if (ordered.length < 2) {
      throw StateError(
        'An evidence block requires at least two messages in one source conversation',
      );
    }
    final categoryRows = db.select(
      '''SELECT category_id FROM category
         WHERE dataset_id=? AND name='Uncategorized' COLLATE NOCASE
         ORDER BY category_id LIMIT 1''',
      [scope.datasetId],
    );
    if (categoryRows.isEmpty) {
      throw StateError(
        'Dataset ${scope.datasetId} has no Uncategorized category',
      );
    }
    final categoryId = categoryRows.first['category_id'] as int;
    final now = DateTime.now().toUtc().toIso8601String();
    late int blockId;
    _write(() {
      db.execute(
        '''INSERT INTO evidence_block(
          dataset_id,category_id,source_thread_id,title,summary,
          context_start_message_id,relevant_start_message_id,core_message_id,
          relevant_end_message_id,context_end_message_id,origin_kind,
          origin_working_corpus_revision_id,origin_scope_hash,created_by,
          created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        [
          scope.datasetId,
          categoryId,
          hit.threadId,
          title ?? 'Evidence at message ${hitOrdinal + 1}',
          summary,
          ordered.first.value,
          hit.id,
          hit.id,
          hit.id,
          ordered.last.value,
          'working_corpus_revision',
          revisionId,
          scope.scopeHash,
          createdBy,
          now,
          now,
        ],
      );
      blockId = db.lastInsertRowId;
      _insertExactRows(
        blockId: blockId,
        revisionId: revisionId,
        sourceThreadId: hit.threadId,
        contextStartOrdinal: ordered.first.key,
        relevantStartOrdinal: hitOrdinal,
        relevantEndOrdinal: hitOrdinal,
        contextEndOrdinal: ordered.last.key,
        highlightedMessageIds: {hit.id},
      );
      db.execute(
        '''INSERT INTO working_corpus_revision_evidence_block(
          working_corpus_revision_id,evidence_block_id,associated_at)
          VALUES (?,?,?)''',
        [revisionId, blockId, now],
      );
      _touchWorkspace(now);
    });
    return evidenceBlock(revisionId, blockId);
  }

  EvidenceBlock createConversationalEvidenceBlock({
    required int revisionId,
    required String startMessageId,
    required String endMessageId,
    required String title,
    required String summary,
    String createdBy = 'conversational_search',
  }) {
    final scope = _readyScope(revisionId);
    late int blockId;
    _write(() {
      final endpoints = db.select(
        '''SELECT w.message_id,w.source_thread_id,w.ordinal
           FROM working_corpus_revision_message w
           WHERE w.working_corpus_revision_id=?
             AND w.message_id IN (?,?)
           ORDER BY w.ordinal''',
        [revisionId, startMessageId, endMessageId],
      );
      final start = endpoints
          .where((row) => row['message_id'] == startMessageId)
          .firstOrNull;
      final end = endpoints
          .where((row) => row['message_id'] == endMessageId)
          .firstOrNull;
      if (start == null || end == null) {
        throw StateError(
          'Conversational evidence endpoints are absent from the selected revision',
        );
      }
      if (start['source_thread_id'] != end['source_thread_id']) {
        throw StateError('Conversational evidence endpoints cross threads');
      }
      final startOrdinal = start['ordinal'] as int;
      final endOrdinal = end['ordinal'] as int;
      if (startOrdinal > endOrdinal) {
        throw StateError('Conversational evidence range is out of order');
      }
      final before = db.select(
        '''SELECT ordinal,message_id
           FROM working_corpus_revision_message
           WHERE working_corpus_revision_id=? AND source_thread_id=?
             AND ordinal<=?
           ORDER BY ordinal DESC LIMIT 4''',
        [revisionId, start['source_thread_id'], startOrdinal],
      );
      final after = db.select(
        '''SELECT ordinal,message_id
           FROM working_corpus_revision_message
           WHERE working_corpus_revision_id=? AND source_thread_id=?
             AND ordinal>=?
           ORDER BY ordinal LIMIT 4''',
        [revisionId, end['source_thread_id'], endOrdinal],
      );
      if (before.isEmpty || after.isEmpty) {
        throw StateError('Conversational evidence context could not be loaded');
      }
      final contextStartOrdinal = before.last['ordinal'] as int;
      final contextEndOrdinal = after.last['ordinal'] as int;
      final categoryRows = db.select(
        '''SELECT category_id FROM category
           WHERE dataset_id=? AND name='Uncategorized' COLLATE NOCASE
           ORDER BY category_id LIMIT 1''',
        [scope.datasetId],
      );
      if (categoryRows.isEmpty) {
        throw StateError(
          'Dataset ${scope.datasetId} has no Uncategorized category',
        );
      }
      final now = DateTime.now().toUtc().toIso8601String();
      final relevantRows = db.select(
        '''SELECT message_id FROM working_corpus_revision_message
           WHERE working_corpus_revision_id=? AND source_thread_id=?
             AND ordinal>=? AND ordinal<=?
           ORDER BY ordinal''',
        [revisionId, start['source_thread_id'], startOrdinal, endOrdinal],
      );
      if (relevantRows.isEmpty) {
        throw StateError('Conversational evidence relevant range is empty');
      }
      final coreMessageId =
          relevantRows[(relevantRows.length - 1) ~/ 2]['message_id'] as String;
      db.execute(
        '''INSERT INTO evidence_block(
          dataset_id,category_id,source_thread_id,title,summary,
          context_start_message_id,relevant_start_message_id,core_message_id,
          relevant_end_message_id,context_end_message_id,origin_kind,
          origin_working_corpus_revision_id,origin_scope_hash,created_by,
          created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        [
          scope.datasetId,
          categoryRows.first['category_id'],
          start['source_thread_id'],
          title,
          summary,
          before.last['message_id'],
          startMessageId,
          coreMessageId,
          endMessageId,
          after.last['message_id'],
          'working_corpus_revision',
          revisionId,
          scope.scopeHash,
          createdBy,
          now,
          now,
        ],
      );
      blockId = db.lastInsertRowId;
      _insertExactRows(
        blockId: blockId,
        revisionId: revisionId,
        sourceThreadId: start['source_thread_id'] as String,
        contextStartOrdinal: contextStartOrdinal,
        relevantStartOrdinal: startOrdinal,
        relevantEndOrdinal: endOrdinal,
        contextEndOrdinal: contextEndOrdinal,
        highlightedMessageIds: {coreMessageId},
      );
      db.execute(
        '''INSERT INTO working_corpus_revision_evidence_block(
          working_corpus_revision_id,evidence_block_id,associated_at)
          VALUES (?,?,?)''',
        [revisionId, blockId, now],
      );
      _touchWorkspace(now);
    });
    return evidenceBlock(revisionId, blockId);
  }

  EvidenceBlock updateEvidenceMetadata({
    required int revisionId,
    required int evidenceBlockId,
    required String title,
    required String summary,
  }) {
    final normalizedTitle = title.trim();
    if (normalizedTitle.isEmpty) {
      throw StateError('Evidence block title cannot be empty');
    }
    final now = DateTime.now().toUtc().toIso8601String();
    _write(() {
      final changed =
          db
                  .select(
                    '''SELECT COUNT(*) AS count FROM working_corpus_revision_evidence_block
           WHERE working_corpus_revision_id=? AND evidence_block_id=?''',
                    [revisionId, evidenceBlockId],
                  )
                  .first['count']
              as int;
      if (changed != 1) {
        throw StateError(
          'Evidence block $evidenceBlockId is not associated with revision $revisionId',
        );
      }
      db.execute(
        'UPDATE evidence_block SET title=?,summary=?,updated_at=? WHERE evidence_block_id=?',
        [normalizedTitle, summary.trim(), now, evidenceBlockId],
      );
      _touchWorkspace(now);
    });
    return evidenceBlock(revisionId, evidenceBlockId);
  }

  EvidenceBlock replaceEvidenceRange({
    required int revisionId,
    required EvidenceBlock block,
  }) {
    if (!(block.contextStartOrdinal <= block.relevantStartOrdinal &&
        block.relevantStartOrdinal <= block.coreOrdinal &&
        block.coreOrdinal <= block.relevantEndOrdinal &&
        block.relevantEndOrdinal <= block.contextEndOrdinal)) {
      throw StateError('Evidence boundaries are out of order');
    }
    if (block.contextStartOrdinal == block.contextEndOrdinal) {
      throw StateError('Evidence context must contain at least two messages');
    }
    final rows = _exactRowsForRange(
      revisionId: revisionId,
      sourceThreadId: block.sourceThreadId,
      contextStartOrdinal: block.contextStartOrdinal,
      contextEndOrdinal: block.contextEndOrdinal,
    );
    if (rows.isEmpty ||
        rows.first['message_id'] != block.contextStartMessageId ||
        rows.last['message_id'] != block.contextEndMessageId) {
      throw StateError('Evidence boundary messages do not match the revision');
    }
    final rangeIds = rows.map((row) => row['message_id'] as String).toSet();
    for (final requiredId in [
      block.relevantStartMessageId,
      block.coreMessageId,
      block.relevantEndMessageId,
    ]) {
      if (!rangeIds.contains(requiredId)) {
        throw StateError('Evidence boundary $requiredId is outside the range');
      }
    }

    final associations = db.select(
      '''SELECT working_corpus_revision_id
         FROM working_corpus_revision_evidence_block
         WHERE evidence_block_id=?''',
      [block.id],
    );
    for (final association in associations) {
      final associatedRevision =
          association['working_corpus_revision_id'] as int;
      final placeholders = List.filled(rangeIds.length, '?').join(',');
      final count =
          db
                  .select(
                    '''SELECT COUNT(*) AS count
                       FROM working_corpus_revision_message
                       WHERE working_corpus_revision_id=?
                         AND message_id IN ($placeholders)''',
                    [associatedRevision, ...rangeIds],
                  )
                  .first['count']
              as int;
      if (count != rangeIds.length) {
        throw StateError(
          'The edited range is incompatible with associated revision $associatedRevision',
        );
      }
    }

    final retainedHighlights = block.highlightedMessageIds
        .where(rangeIds.contains)
        .toSet();
    final now = DateTime.now().toUtc().toIso8601String();
    _write(() {
      db.execute(
        'DELETE FROM evidence_block_message WHERE evidence_block_id=?',
        [block.id],
      );
      db.execute(
        '''UPDATE evidence_block SET
          context_start_message_id=?,relevant_start_message_id=?,
          core_message_id=?,relevant_end_message_id=?,
          context_end_message_id=?,updated_at=?
          WHERE evidence_block_id=?''',
        [
          block.contextStartMessageId,
          block.relevantStartMessageId,
          block.coreMessageId,
          block.relevantEndMessageId,
          block.contextEndMessageId,
          now,
          block.id,
        ],
      );
      _insertExactRows(
        blockId: block.id,
        revisionId: revisionId,
        sourceThreadId: block.sourceThreadId,
        contextStartOrdinal: block.contextStartOrdinal,
        relevantStartOrdinal: block.relevantStartOrdinal,
        relevantEndOrdinal: block.relevantEndOrdinal,
        contextEndOrdinal: block.contextEndOrdinal,
        highlightedMessageIds: retainedHighlights,
      );
      _touchWorkspace(now);
    });
    return evidenceBlock(revisionId, block.id);
  }

  EvidenceBlock updateCoreMessage({
    required int revisionId,
    required int evidenceBlockId,
    required String messageId,
  }) {
    final block = evidenceBlock(revisionId, evidenceBlockId);
    final ordinal = ordinalForMessage(revisionId, messageId);
    if (ordinal == null ||
        ordinal < block.relevantStartOrdinal ||
        ordinal > block.relevantEndOrdinal ||
        !block.messageIds.contains(messageId)) {
      throw StateError('Primary message must remain inside the relevant range');
    }
    final now = DateTime.now().toUtc().toIso8601String();
    _write(() {
      db.execute(
        'UPDATE evidence_block SET core_message_id=?,updated_at=? WHERE evidence_block_id=?',
        [messageId, now, evidenceBlockId],
      );
      _touchWorkspace(now);
    });
    return evidenceBlock(revisionId, evidenceBlockId);
  }

  EvidenceBlock toggleEvidenceHighlight({
    required int revisionId,
    required int evidenceBlockId,
    required String messageId,
  }) {
    final block = evidenceBlock(revisionId, evidenceBlockId);
    if (!block.messageIds.contains(messageId)) {
      throw StateError(
        'Highlight message $messageId is outside evidence block $evidenceBlockId',
      );
    }
    final now = DateTime.now().toUtc().toIso8601String();
    _write(() {
      if (block.highlightedMessageIds.contains(messageId)) {
        db.execute(
          'DELETE FROM evidence_block_highlight WHERE evidence_block_id=? AND message_id=?',
          [evidenceBlockId, messageId],
        );
      } else {
        db.execute(
          'INSERT INTO evidence_block_highlight(evidence_block_id,message_id) VALUES (?,?)',
          [evidenceBlockId, messageId],
        );
      }
      db.execute(
        'UPDATE evidence_block SET updated_at=? WHERE evidence_block_id=?',
        [now, evidenceBlockId],
      );
      _touchWorkspace(now);
    });
    return evidenceBlock(revisionId, evidenceBlockId);
  }

  void deleteEvidenceBlock({
    required int revisionId,
    required int evidenceBlockId,
  }) {
    final now = DateTime.now().toUtc().toIso8601String();
    _write(() {
      final associated =
          db
                  .select(
                    '''SELECT COUNT(*) AS count
                       FROM working_corpus_revision_evidence_block
                       WHERE working_corpus_revision_id=?
                         AND evidence_block_id=?''',
                    [revisionId, evidenceBlockId],
                  )
                  .first['count']
              as int;
      if (associated != 1) {
        throw StateError(
          'Evidence block $evidenceBlockId is not associated with revision $revisionId',
        );
      }
      db.execute('DELETE FROM evidence_block WHERE evidence_block_id=?', [
        evidenceBlockId,
      ]);
      _touchWorkspace(now);
    });
  }

  List<Row> _exactRowsForRange({
    required int revisionId,
    required String sourceThreadId,
    required int contextStartOrdinal,
    required int contextEndOrdinal,
  }) => db.select(
    '''SELECT w.ordinal,m.message_id,m.timestamp,m.sender_display,m.body
       FROM working_corpus_revision_message w
       JOIN message m ON m.message_id=w.message_id
       WHERE w.working_corpus_revision_id=? AND w.source_thread_id=?
         AND w.ordinal>=? AND w.ordinal<=?
       ORDER BY w.ordinal''',
    [revisionId, sourceThreadId, contextStartOrdinal, contextEndOrdinal],
  );

  void _insertExactRows({
    required int blockId,
    required int revisionId,
    required String sourceThreadId,
    required int contextStartOrdinal,
    required int relevantStartOrdinal,
    required int relevantEndOrdinal,
    required int contextEndOrdinal,
    required Set<String> highlightedMessageIds,
  }) {
    final rows = _exactRowsForRange(
      revisionId: revisionId,
      sourceThreadId: sourceThreadId,
      contextStartOrdinal: contextStartOrdinal,
      contextEndOrdinal: contextEndOrdinal,
    );
    if (rows.length < 2) {
      throw StateError('Evidence context must contain at least two messages');
    }
    final validIds = <String>{};
    for (var index = 0; index < rows.length; index++) {
      final row = rows[index];
      final ordinal = row['ordinal'] as int;
      final messageId = row['message_id'] as String;
      validIds.add(messageId);
      final section = ordinal < relevantStartOrdinal
          ? 'leading_context'
          : ordinal <= relevantEndOrdinal
          ? 'relevant'
          : 'trailing_context';
      final contentHash = sha256
          .convert(
            utf8.encode(
              jsonEncode([
                messageId,
                row['timestamp'] as String,
                row['sender_display'] as String,
                row['body'] as String,
              ]),
            ),
          )
          .toString();
      db.execute(
        '''INSERT INTO evidence_block_message(
          evidence_block_id,message_id,ordinal,section,message_content_hash)
          VALUES (?,?,?,?,?)''',
        [blockId, messageId, index, section, contentHash],
      );
    }
    for (final messageId in highlightedMessageIds) {
      if (!validIds.contains(messageId)) {
        throw StateError(
          'Highlight message $messageId is outside evidence block $blockId',
        );
      }
      db.execute(
        'INSERT INTO evidence_block_highlight(evidence_block_id,message_id) VALUES (?,?)',
        [blockId, messageId],
      );
    }
  }

  _ReadyScope _readyScope(int revisionId) {
    final rows = db.select(
      '''SELECT wc.dataset_id,r.scope_hash,r.status
         FROM working_corpus_revision r
         JOIN working_corpus wc ON wc.working_corpus_id=r.working_corpus_id
         WHERE r.working_corpus_revision_id=?''',
      [revisionId],
    );
    if (rows.isEmpty) throw StateError('Revision $revisionId does not exist');
    final row = rows.first;
    if (row['status'] != 'ready') {
      throw StateError('Revision $revisionId is not ready');
    }
    return _ReadyScope(row['dataset_id'] as int, row['scope_hash'] as String);
  }

  void _touchWorkspace(String now) {
    db.execute("UPDATE workspace_state SET value=? WHERE key='updated_at'", [
      now,
    ]);
  }

  T _write<T>(T Function() operation) {
    db.execute('BEGIN IMMEDIATE');
    try {
      final result = operation();
      db.execute('COMMIT');
      return result;
    } catch (_) {
      db.execute('ROLLBACK');
      rethrow;
    }
  }

  void checkpoint() {
    final row = db.select('PRAGMA wal_checkpoint(PASSIVE)').first;
    if ((row.columnAt(0) as int) != 0) {
      throw StateError(
        'WAL checkpoint was busy: ${row.columnAt(0)}, '
        '${row.columnAt(1)}, ${row.columnAt(2)}',
      );
    }
  }

  void close() {
    if (_closed) return;
    _closed = true;
    Object? closeError;
    try {
      if (_lockFile != null) {
        db.execute('BEGIN IMMEDIATE');
        db.execute(
          "UPDATE workspace_state SET value='0' WHERE key='workspace_open'",
        );
        db.execute('COMMIT');
        final row = db.select('PRAGMA wal_checkpoint(TRUNCATE)').first;
        if ((row.columnAt(0) as int) != 0) {
          closeError = StateError(
            'WAL checkpoint was busy during close: ${row.columnAt(0)}, '
            '${row.columnAt(1)}, ${row.columnAt(2)}',
          );
        }
      }
    } catch (error) {
      closeError = error;
    } finally {
      db.dispose();
      if (_lockFile != null) {
        try {
          _lockFile.unlockSync(0, 1);
        } finally {
          _lockFile.closeSync();
        }
      }
    }
    if (closeError != null) throw closeError;
  }
}

class _ReadyScope {
  const _ReadyScope(this.datasetId, this.scopeHash);
  final int datasetId;
  final String scopeHash;
}
