import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:evw_client/src/conversation_workflow.dart';
import 'package:evw_client/src/evw_database.dart';
import 'package:evw_client/src/evw_models.dart';
import 'package:evw_client/src/native_extensions.dart';
import 'package:evw_client/src/server_contracts.dart';
import 'package:evw_client/src/server_gateway.dart';
import 'package:evw_client/src/workspace_controller.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqlite3/sqlite3.dart';

void main() {
  test(
    'conversation freezes the full transcript and persists only visible history',
    () async {
      final fixture = _ConversationFixture();
      addTearDown(fixture.close);
      final events = <ConversationProgress>[];

      final result = await ConversationWorkflow(
        workspace: fixture.workspace,
      ).run('What happened?', onProgress: events.add);

      expect(result.result['overview'], 'A complete answer.');
      expect(
        events.map((item) => item.phase),
        containsAll(['planning_completed', 'completed', 'persisted']),
      );
      expect(
        fixture.fakeGateway.analysisPayload['working_corpus']['messages'],
        hasLength(2),
      );
      expect(
        fixture.fakeGateway.analysisPayload['analysis_context']['hits'],
        isEmpty,
      );
      expect(
        fixture.raw
            .select('SELECT COUNT(*) AS count FROM conversation')
            .first['count'],
        1,
      );
      expect(
        fixture.raw
            .select('SELECT user_prompt FROM conversation_turn')
            .first['user_prompt'],
        'What happened?',
      );
      expect(
        fixture.raw
            .select('SELECT COUNT(*) AS count FROM conversation_citation')
            .first['count'],
        0,
      );
      expect(fixture.workspace.remoteOperationActive, isFalse);
    },
  );

  test(
    'conversation failure releases the lease and does not persist an incomplete turn',
    () async {
      final fixture = _ConversationFixture(failAnalysis: true);
      addTearDown(fixture.close);

      await expectLater(
        ConversationWorkflow(workspace: fixture.workspace).run('Fail now'),
        throwsA(isA<GatewayError>()),
      );
      expect(fixture.workspace.remoteOperationActive, isFalse);
      expect(
        fixture.raw
            .select('SELECT COUNT(*) AS count FROM conversation')
            .first['count'],
        0,
      );
    },
  );

  test(
    'semantic conversation embeds every planner query before local candidate assembly',
    () async {
      loadSqliteVec();
      final fixture = _ConversationFixture(semantic: true);
      addTearDown(fixture.close);

      final result = await ConversationWorkflow(
        workspace: fixture.workspace,
      ).run('Find events');

      expect(result.mode, 'semantic_ranges');
      expect(fixture.fakeGateway.embeddingItems, hasLength(2));
      expect(
        fixture.fakeGateway.analysisPayload['analysis_context']['hits'],
        isNotEmpty,
      );
    },
  );

  test(
    'clarification planner result stops before analysis and preserves all three values on the next pass',
    () async {
      final gateway = _ClarifyingGateway();
      final fixture = _ConversationFixture(gatewayOverride: gateway);
      addTearDown(fixture.close);

      final first = await ConversationWorkflow(
        workspace: fixture.workspace,
      ).run('When did we discuss school?');

      expect(first.needsClarification, isTrue);
      expect(first.clarificationQuestion, 'Which school matter?');
      expect(gateway.histories, hasLength(1));
      expect(gateway.histories.single, isEmpty);
      expect(fixture.workspace.remoteOperationActive, isFalse);
      expect(fixture.fakeGateway.analysisCalled, isFalse);

      final second = await ConversationWorkflow(workspace: fixture.workspace)
          .run(
            'When did we discuss school?',
            clarificationHistory: const [
              {
                'question': 'Which school matter?',
                'answer': 'The 2024 dispute.',
              },
            ],
          );

      expect(second.disposition, 'analyze_corpus');
      expect(gateway.histories, hasLength(2));
      expect(gateway.histories.last, [
        {'question': 'Which school matter?', 'answer': 'The 2024 dispute.'},
      ]);
      expect(
        fixture.fakeGateway.analysisPayload['question'],
        'When did we discuss school?',
      );
    },
  );

  test(
    'real HTTP gateway and coordinator complete and persist a conversation',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final gateway = HttpServerGateway(
        'http://127.0.0.1:${server.port}',
        timeout: const Duration(seconds: 2),
      );
      final fixture = _ConversationFixture(gatewayOverride: gateway);
      addTearDown(() async {
        fixture.close();
        gateway.close();
        await server.close(force: true);
      });
      server.listen((request) async {
        final body =
            jsonDecode(await utf8.decoder.bind(request).join())
                as Map<String, dynamic>;
        final requestId = body['request_id'] as String;
        if (request.uri.path == '/v1/conversational-plan') {
          final fake = _FakeGateway(failAnalysis: false, semantic: false);
          final plan = await fake.conversationalPlan(
            body['question'] as String,
          );
          request.response.headers.contentType = ContentType.json;
          request.response.write(
            jsonEncode({...plan.value, 'request_id': requestId}),
          );
        } else if (request.uri.path == '/v1/conversational-analysis') {
          request.response.headers.contentType = ContentType(
            'application',
            'x-ndjson',
          );
          final fake = _FakeGateway(failAnalysis: false, semantic: false);
          await for (final event in fake.conversationalAnalysis(body)) {
            request.response.writeln(
              jsonEncode({...event.value, 'request_id': requestId}),
            );
          }
        } else {
          request.response.statusCode = HttpStatus.notFound;
        }
        await request.response.close();
      });

      final result = await ConversationWorkflow(
        workspace: fixture.workspace,
      ).run('What happened over HTTP?');

      expect(result.result['overview'], 'A complete answer.');
      expect(
        fixture.raw
            .select('SELECT COUNT(*) AS count FROM conversation')
            .first['count'],
        1,
      );
    },
  );
}

class _ConversationFixture {
  _ConversationFixture({
    this.failAnalysis = false,
    this.semantic = false,
    ServerGateway? gatewayOverride,
  }) {
    raw = sqlite3.openInMemory();
    raw.execute('''
      CREATE TABLE workspace_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      INSERT INTO workspace_state VALUES ('updated_at','');
      CREATE TABLE working_corpus(working_corpus_id INTEGER PRIMARY KEY,dataset_id INTEGER NOT NULL,name TEXT,current_revision_id INTEGER);
      CREATE TABLE working_corpus_revision(working_corpus_revision_id INTEGER PRIMARY KEY,working_corpus_id INTEGER,status TEXT,message_count INTEGER,scope_hash TEXT);
      CREATE TABLE working_corpus_revision_index(working_corpus_revision_id INTEGER,index_generation INTEGER,status TEXT,fts_status TEXT,message_embedding_status TEXT,chunk_embedding_status TEXT);
      CREATE TABLE source_thread(source_thread_id TEXT PRIMARY KEY,display_title TEXT);
      CREATE TABLE message(message_id TEXT PRIMARY KEY,source_thread_id TEXT,timestamp TEXT,sender_display TEXT,body TEXT,embedding_input_hash TEXT,sort_index INTEGER);
      CREATE TABLE working_corpus_revision_message(working_corpus_revision_id INTEGER,message_id TEXT,source_thread_id TEXT,ordinal INTEGER,token_count INTEGER,embedding_input_hash TEXT,PRIMARY KEY(working_corpus_revision_id,message_id));
      CREATE TABLE embedding_cache_state(cache_id INTEGER PRIMARY KEY,dimensions INTEGER,normalization TEXT);
      CREATE TABLE embedding_artifact(input_hash TEXT PRIMARY KEY,dimensions INTEGER,vector BLOB);
      CREATE TABLE conversation(conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,dataset_id INTEGER,working_corpus_id INTEGER,working_corpus_revision_id INTEGER,index_generation INTEGER,scope_hash TEXT,created_at TEXT,status TEXT);
      CREATE TABLE conversation_turn(conversation_turn_id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id INTEGER,working_corpus_id INTEGER,working_corpus_revision_id INTEGER,index_generation INTEGER,scope_hash TEXT,user_prompt TEXT,presented_answer TEXT,mode TEXT,status TEXT,created_at TEXT);
      CREATE TABLE conversation_citation(conversation_citation_id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_turn_id INTEGER,message_id TEXT,citation_type TEXT);
    ''');
    raw.execute("INSERT INTO working_corpus VALUES (1,1,'Corpus',1)");
    raw.execute(
      "INSERT INTO working_corpus_revision VALUES (1,1,'ready',2,'scope-hash')",
    );
    raw.execute(
      "INSERT INTO working_corpus_revision_index VALUES (1,1,'ready','ready','ready','missing')",
    );
    raw.execute("INSERT INTO source_thread VALUES ('thread-1','Thread')");
    raw.execute("INSERT INTO message VALUES (?,?,?,?,?,?,?)", [
      'm1',
      'thread-1',
      '2026-01-01T00:00:00Z',
      'A',
      'First',
      'a' * 64,
      0,
    ]);
    raw.execute("INSERT INTO message VALUES (?,?,?,?,?,?,?)", [
      'm2',
      'thread-1',
      '2026-01-01T00:01:00Z',
      'B',
      'Second',
      'b' * 64,
      1,
    ]);
    raw.execute(
      "INSERT INTO working_corpus_revision_message VALUES (?,?,?,?,?,?)",
      [1, 'm1', 'thread-1', 0, 1, 'a' * 64],
    );
    raw.execute(
      "INSERT INTO working_corpus_revision_message VALUES (?,?,?,?,?,?)",
      [1, 'm2', 'thread-1', 1, 1, 'b' * 64],
    );
    if (semantic) {
      raw.execute("INSERT INTO embedding_cache_state VALUES (1,2,'unit_l2')");
      raw.execute('INSERT INTO embedding_artifact VALUES (?,?,?)', [
        'a' * 64,
        2,
        _vectorBytes([0.6, 0.8]),
      ]);
      raw.execute('INSERT INTO embedding_artifact VALUES (?,?,?)', [
        'b' * 64,
        2,
        _vectorBytes([0.8, 0.6]),
      ]);
    }
    database = EvwDatabase.forTesting(raw);
    gateway =
        gatewayOverride ??
        _FakeGateway(failAnalysis: failAnalysis, semantic: semantic);
    workspace = WorkspaceController(gateway: gateway)
      ..database = database
      ..corpora = [const CorpusSummary(1, 'Corpus', 1)]
      ..selectedCorpus = const CorpusSummary(1, 'Corpus', 1)
      ..selectedRevision = const RevisionSummary(
        id: 1,
        corpusId: 1,
        datasetId: 1,
        number: 1,
        status: 'ready',
        messages: 2,
        tokens: 2,
        scopeHash: 'scope-hash',
        generation: 1,
        messageEmbeddingStatus: null,
        chunkEmbeddingStatus: null,
      );
  }

  final bool failAnalysis;
  final bool semantic;
  late final Database raw;
  late final EvwDatabase database;
  late final ServerGateway gateway;
  late final WorkspaceController workspace;

  _FakeGateway get fakeGateway => gateway as _FakeGateway;

  void close() {
    workspace.dispose();
  }
}

class _FakeGateway implements ServerGateway {
  _FakeGateway({required this.failAnalysis, required this.semantic});

  final bool failAnalysis;
  final bool semantic;
  late Map<String, dynamic> analysisPayload;
  bool analysisCalled = false;
  List<Map<String, String>> embeddingItems = const [];

  @override
  String get baseUrl => 'fake://gateway';

  @override
  Future<AnalysisPlanContract> conversationalPlan(
    String question, {
    int maximumPromptSuggestionMessages = 40,
    RequestCancellation? cancellation,
  }) async => AnalysisPlanContract({
    'request_id': '11111111-1111-4111-8111-111111111111',
    'config_version': 1,
    'analysis_plan_id': '22222222-2222-4222-8222-222222222222',
    'compatibility_fingerprint': List.filled(64, 'a').join(),
    'analysis_plan': {
      'analysis_question': question,
      'answer_objective': 'Answer the question.',
      'concepts': [
        {
          'label': 'event',
          'definition': 'An event',
          'manifestations': ['event'],
        },
      ],
      'inclusion_criteria': ['direct evidence'],
      'exclusion_criteria': [],
      'answer_requirements': ['be clear'],
      'interpretive_assumptions': [],
    },
    'retrieval_queries': [
      {'query_id': 'q0001', 'text': 'event'},
      if (semantic) {'query_id': 'q0002', 'text': 'meeting'},
    ],
    'embedding': semantic
        ? {
            'embedding_profile_id': 'profile',
            'artifact_fingerprint': List.filled(64, 'a').join(),
            'dimensions': 2,
            'normalization': 'unit_l2',
          }
        : null,
    'search_policy': {
      'mode': semantic ? 'semantic_ranges' : 'none',
      'top_k_per_query': 20,
      'fusion_method': 'reciprocal_rank_fusion',
      'rrf_constant': 60,
      'maximum_prompt_suggestion_messages': 50,
    },
    'usage': {
      'input_tokens': 1,
      'output_tokens': 1,
      'source': 'estimated',
      'estimated_cost': 0.0,
      'cost_complete': true,
      'currency': 'USD',
    },
  });

  @override
  Stream<ServerEvent> embeddings(
    List<Map<String, String>> items, {
    RequestCancellation? cancellation,
  }) async* {
    if (!semantic) throw StateError('This fixture does not request embeddings');
    embeddingItems = items;
    const requestId = '44444444-4444-4444-8444-444444444444';
    yield ServerEvent({
      'request_id': requestId,
      'sequence': 1,
      'event': 'accepted',
      'timestamp': '2026-01-01T00:00:00Z',
      'config_version': 1,
      'data': {
        'endpoint': '/v1/embeddings',
        'total_items': 2,
        'embedding_profile_id': 'profile',
        'model': 'fixture',
        'requested_revision': 'fixture',
        'artifact_fingerprint': List.filled(64, 'a').join(),
        'dimensions': 2,
        'normalization': 'unit_l2',
      },
    });
    yield ServerEvent({
      'request_id': requestId,
      'sequence': 2,
      'event': 'vector_batch',
      'timestamp': '2026-01-01T00:00:00Z',
      'config_version': 1,
      'data': {
        'batch_index': 0,
        'items': items
            .map(
              (item) => {
                'message_id': item['message_id'],
                'vector': [0.6, 0.8],
              },
            )
            .toList(),
      },
    });
    yield ServerEvent({
      'request_id': requestId,
      'sequence': 3,
      'event': 'completed',
      'timestamp': '2026-01-01T00:00:00Z',
      'config_version': 1,
      'result': {'total_items': 2, 'embedding_profile_id': 'profile'},
    });
  }

  @override
  Stream<ServerEvent> conversationalAnalysis(
    Map<String, dynamic> payload, {
    RequestCancellation? cancellation,
  }) async* {
    analysisCalled = true;
    analysisPayload = payload;
    yield ServerEvent({
      'request_id': '33333333-3333-4333-8333-333333333333',
      'sequence': 1,
      'event': 'accepted',
      'timestamp': '2026-01-01T00:00:00Z',
      'config_version': 1,
      'data': {
        'endpoint': '/v1/conversational-analysis',
        'scope_id': 'scope',
        'message_count': 2,
      },
    });
    if (failAnalysis) {
      yield ServerEvent({
        'request_id': '33333333-3333-4333-8333-333333333333',
        'sequence': 2,
        'event': 'failed',
        'timestamp': '2026-01-01T00:00:01Z',
        'config_version': 1,
        'error': {
          'request_id': '33333333-3333-4333-8333-333333333333',
          'code': 'TEST_FAILURE',
          'message': 'Fixture failure',
          'stage': 'test',
          'retryable': false,
          'details': {'reason': 'fixture'},
        },
      });
      return;
    }
    yield ServerEvent({
      'request_id': '33333333-3333-4333-8333-333333333333',
      'sequence': 2,
      'event': 'completed',
      'timestamp': '2026-01-01T00:00:01Z',
      'config_version': 1,
      'result': {
        'completion_status': 'complete',
        'answer_source': 'structured_synthesis',
        'overview': 'A complete answer.',
        'raw_answer': null,
        'results': [],
        'unclassified_evidence': [],
        'unverified_model_statements': [],
        'evidence_ledger': [],
        'evidence_validation': {
          'planned_window_count': 0,
          'usable_window_count': 0,
          'unavailable_window_count': 0,
          'unavailable_windows': [],
          'status': 'complete',
          'accepted_range_count': 0,
          'rejected_range_count': 0,
          'normalized_range_count': 0,
          'rejected_ranges': [],
          'warnings': [],
        },
        'synthesis_validation': {
          'status': 'conformant',
          'raw_output_preserved': false,
          'warnings': [],
        },
        'coverage': {
          'message_count': 2,
          'planned_window_count': 0,
          'usable_window_count': 0,
          'unavailable_window_count': 0,
          'evidence_range_count': 0,
        },
        'retrieval_diagnostics': {
          'mode': 'none',
          'query_count': 1,
          'raw_hit_count': 0,
          'unique_candidate_message_count': 0,
          'selected_suggestion_message_count': 0,
          'suggestion_range_count': 0,
          'final_ranges_overlapping_suggestions': 0,
          'final_ranges_outside_suggestions': 0,
          'answer_relevant_ranges_overlapping_suggestions': 0,
          'answer_relevant_ranges_outside_suggestions': 0,
          'suggestions_without_final_evidence': 0,
        },
        'ledger_processing': {
          'direct_synthesis_input_tokens': 0,
          'synthesis_usable_input_tokens': 0,
          'compaction_applied': false,
          'compaction_levels': 0,
          'compaction_group_calls': 0,
        },
        'usage': {
          'input_tokens': 0,
          'output_tokens': 0,
          'source': 'estimated',
          'estimated_cost': 0.0,
          'cost_complete': true,
          'currency': 'USD',
        },
        'uncertainties': [],
        'strategy': 'single_window_ledger',
      },
    });
  }
}

class _ClarifyingGateway extends _FakeGateway
    implements ClarificationCapableGateway {
  _ClarifyingGateway() : super(failAnalysis: false, semantic: false);

  final List<List<Map<String, String>>> histories = [];

  @override
  Future<AnalysisPlanContract> conversationalPlanWithClarification(
    String question, {
    int maximumPromptSuggestionMessages = 40,
    List<Map<String, String>> clarificationHistory = const [],
    RequestCancellation? cancellation,
  }) async {
    histories.add(
      clarificationHistory
          .map((entry) => Map<String, String>.from(entry))
          .toList(),
    );
    if (clarificationHistory.isEmpty) {
      return AnalysisPlanContract({
        'request_id': '11111111-1111-4111-8111-111111111111',
        'config_version': 1,
        'disposition': 'needs_clarification',
        'clarification_question': 'Which school matter?',
        'usage': {
          'input_tokens': 1,
          'output_tokens': 1,
          'source': 'estimated',
          'estimated_cost': 0.0,
          'cost_complete': true,
          'currency': 'USD',
        },
      });
    }
    return conversationalPlan(
      question,
      maximumPromptSuggestionMessages: maximumPromptSuggestionMessages,
      cancellation: cancellation,
    );
  }
}

Uint8List _vectorBytes(List<double> values) {
  final bytes = ByteData(values.length * 4);
  for (var index = 0; index < values.length; index++) {
    bytes.setFloat32(index * 4, values[index], Endian.little);
  }
  return bytes.buffer.asUint8List();
}
