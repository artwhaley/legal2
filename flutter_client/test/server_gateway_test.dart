import 'dart:convert';
import 'dart:io';

import 'package:evw_client/src/server_contracts.dart';
import 'package:evw_client/src/server_gateway.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late HttpServer server;
  late HttpServerGateway gateway;

  setUp(() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    gateway = HttpServerGateway('http://127.0.0.1:${server.port}');
  });

  tearDown(() async {
    gateway.close();
    await server.close(force: true);
  });

  test(
    'gateway validates JSON planning and NDJSON embedding streams',
    () async {
      final seenRequestIds = <String>[];
      final seenSuggestionLimits = <int>[];
      server.listen((request) async {
        final body = jsonDecode(await utf8.decoder.bind(request).join()) as Map;
        final requestId = body['request_id'] as String;
        seenRequestIds.add(requestId);
        if (request.uri.path == '/v1/conversational-plan') {
          seenSuggestionLimits.add(
            body['maximum_prompt_suggestion_messages'] as int,
          );
          request.response.headers.contentType = ContentType.json;
          request.response.write(jsonEncode(_plan(requestId)));
        } else {
          request.response.headers.contentType = ContentType(
            'application',
            'x-ndjson',
          );
          final events = [
            _event(requestId, 1, 'accepted', {
              'endpoint': '/v1/embeddings',
              'total_items': 1,
              'embedding_profile_id': 'profile',
              'model': 'test-model',
              'requested_revision': '',
              'artifact_fingerprint': List.filled(64, 'a').join(),
              'dimensions': 2,
              'normalization': 'unit_l2',
            }),
            _event(requestId, 2, 'vector_batch', {
              'batch_index': 0,
              'items': [
                {
                  'message_id': 'query',
                  'vector': [0.6, 0.8],
                },
              ],
            }),
            _event(requestId, 3, 'completed', {
              'total_items': 1,
              'embedding_profile_id': 'profile',
            }),
          ];
          request.response.write(events.map(jsonEncode).join('\n'));
        }
        await request.response.close();
      });

      final plan = await gateway.conversationalPlan(
        'Question?',
        maximumPromptSuggestionMessages: 23,
      );
      expect(plan.planId, '22222222-2222-4222-8222-222222222222');
      final received = <ServerEvent>[];
      await for (final event in gateway.embeddings([
        {'message_id': 'query', 'text': 'question'},
      ])) {
        received.add(event);
      }
      expect(received.map((event) => event.event), [
        'accepted',
        'vector_batch',
        'completed',
      ]);
      expect(seenRequestIds, hasLength(2));
      expect(seenRequestIds.toSet(), hasLength(2));
      expect(seenSuggestionLimits, [23]);
    },
  );

  test('gateway rejects a stream with a non-increasing sequence', () async {
    server.listen((request) async {
      final body = jsonDecode(await utf8.decoder.bind(request).join()) as Map;
      final requestId = body['request_id'] as String;
      request.response.headers.contentType = ContentType(
        'application',
        'x-ndjson',
      );
      request.response.write(
        '${jsonEncode(_event(requestId, 2, 'accepted', {'endpoint': '/v1/embeddings', 'total_items': 1, 'embedding_profile_id': 'profile', 'model': 'test-model', 'requested_revision': 'revision', 'artifact_fingerprint': List.filled(64, 'a').join(), 'dimensions': 2, 'normalization': 'unit_l2'}))}\n',
      );
      await request.response.close();
    });

    await expectLater(
      gateway.embeddings([
        {'message_id': 'query', 'text': 'question'},
      ]).drain<void>(),
      throwsA(isA<GatewayValidationError>()),
    );
  });

  test('JSON response body has a bounded inactivity timeout', () async {
    gateway.close();
    gateway = HttpServerGateway(
      'http://127.0.0.1:${server.port}',
      timeout: const Duration(milliseconds: 100),
    );
    server.listen((request) async {
      await utf8.decoder.bind(request).join();
      request.response.headers.contentType = ContentType.json;
      request.response.write('{"request_id":');
      await request.response.flush();
    });

    await expectLater(
      gateway.conversationalPlan('Question?'),
      throwsA(
        isA<GatewayError>().having(
          (error) => error.message,
          'message',
          'Server request timed out',
        ),
      ),
    );
  });

  test('NDJSON stream has a bounded inactivity timeout', () async {
    gateway.close();
    gateway = HttpServerGateway(
      'http://127.0.0.1:${server.port}',
      timeout: const Duration(milliseconds: 100),
    );
    server.listen((request) async {
      final body = jsonDecode(await utf8.decoder.bind(request).join()) as Map;
      final requestId = body['request_id'] as String;
      request.response.headers.contentType = ContentType(
        'application',
        'x-ndjson',
      );
      request.response.writeln(
        jsonEncode(
          _event(requestId, 1, 'accepted', {
            'endpoint': '/v1/embeddings',
            'total_items': 1,
            'embedding_profile_id': 'profile',
            'model': 'test-model',
            'requested_revision': 'revision',
            'artifact_fingerprint': List.filled(64, 'a').join(),
            'dimensions': 2,
            'normalization': 'unit_l2',
          }),
        ),
      );
      await request.response.flush();
    });

    await expectLater(
      gateway.embeddings([
        {'message_id': 'query', 'text': 'question'},
      ]).drain<void>(),
      throwsA(
        isA<GatewayError>().having(
          (error) => error.message,
          'message',
          'Server stream timed out',
        ),
      ),
    );
  });
}

Map<String, dynamic> _plan(String requestId) => {
  'request_id': requestId,
  'config_version': 1,
  'analysis_plan_id': '22222222-2222-4222-8222-222222222222',
  'compatibility_fingerprint': List.filled(64, 'a').join(),
  'analysis_plan': {
    'analysis_question': 'Question?',
    'answer_objective': 'Answer.',
    'concepts': [
      {
        'label': 'event',
        'definition': 'Event',
        'manifestations': ['event'],
      },
    ],
    'inclusion_criteria': ['direct'],
    'exclusion_criteria': [],
    'answer_requirements': ['clear'],
    'interpretive_assumptions': [],
  },
  'retrieval_queries': [
    {'query_id': 'q0001', 'text': 'event'},
  ],
  'embedding': null,
  'search_policy': {
    'mode': 'none',
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
};

Map<String, dynamic> _event(
  String requestId,
  int sequence,
  String event,
  Map<String, dynamic> data,
) => {
  'request_id': requestId,
  'sequence': sequence,
  'event': event,
  'timestamp': '2026-01-01T00:00:00Z',
  'config_version': 1,
  event == 'completed' ? 'result' : 'data': data,
};
