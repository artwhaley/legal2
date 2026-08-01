import 'dart:convert';

import 'evw_database.dart';
import 'evw_models.dart';
import 'server_contracts.dart';
import 'server_gateway.dart';
import 'workspace_controller.dart';

class ConversationProgress {
  const ConversationProgress({
    required this.phase,
    required this.message,
    required this.elapsed,
    this.event,
    this.metadata = const {},
  });

  final String phase;
  final String message;
  final Duration elapsed;
  final ServerEvent? event;
  final Map<String, dynamic> metadata;
}

class ConversationExecutionResult {
  const ConversationExecutionResult({
    required this.question,
    required this.result,
    required this.presentedAnswer,
    required this.mode,
    required this.progress,
  });

  final String question;
  final Map<String, dynamic> result;
  final String presentedAnswer;
  final String mode;
  final List<ConversationProgress> progress;
}

typedef ConversationProgressCallback = void Function(ConversationProgress);

class ConversationWorkflow {
  ConversationWorkflow({required this.workspace});

  final WorkspaceController workspace;

  Future<ConversationExecutionResult> run(
    String question, {
    int maximumPromptSuggestionMessages = 40,
    RequestCancellation? cancellation,
    ConversationProgressCallback? onProgress,
  }) async {
    final normalizedQuestion = question.trim();
    if (normalizedQuestion.isEmpty) {
      throw ArgumentError('Question cannot be blank');
    }
    if (maximumPromptSuggestionMessages < 1 ||
        maximumPromptSuggestionMessages > 500) {
      throw ArgumentError.value(
        maximumPromptSuggestionMessages,
        'maximumPromptSuggestionMessages',
        'must be between 1 and 500',
      );
    }
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    final corpus = workspace.selectedCorpus;
    if (database == null || revision == null || corpus == null) {
      throw StateError(
        'Select a ready working corpus revision before asking a question',
      );
    }
    if (revision.messages < 1 || revision.generation == null) {
      throw StateError(
        'The selected revision has no usable messages or index generation',
      );
    }

    final lease = workspace.beginRemoteOperation('conversation analysis');
    final stopwatch = Stopwatch()..start();
    final progress = <ConversationProgress>[];
    void publish(
      String phase,
      String message, {
      ServerEvent? event,
      Map<String, dynamic> metadata = const {},
    }) {
      final item = ConversationProgress(
        phase: phase,
        message: message,
        elapsed: stopwatch.elapsed,
        event: event,
        metadata: metadata,
      );
      progress.add(item);
      onProgress?.call(item);
    }

    try {
      cancellation?.checkpoint();
      publish(
        'planning_started',
        'Requesting an analysis plan from the server.',
      );
      final plan = await workspace.gateway.conversationalPlan(
        normalizedQuestion,
        maximumPromptSuggestionMessages: maximumPromptSuggestionMessages,
        cancellation: cancellation,
      );
      cancellation?.checkpoint();
      publish(
        'planning_completed',
        'Analysis Plan Ready.',
        metadata: {
          'analysis_question': plan.analysisPlan['analysis_question'],
          'retrieval_queries': plan.retrievalQueries
              .map((query) => query['text'])
              .whereType<String>()
              .toList(growable: false),
        },
      );

      final mode = plan.searchPolicy['mode'] as String;
      final hits = mode == 'none'
          ? <Map<String, dynamic>>[]
          : await _retrieveSemanticHits(
              database,
              revision,
              plan,
              cancellation: cancellation,
              publish: publish,
            );
      final context = <String, dynamic>{
        'analysis_plan_id': plan.planId,
        'plan_config_version': plan.configVersion,
        'compatibility_fingerprint': plan.value['compatibility_fingerprint'],
        'analysis_plan': plan.analysisPlan,
        'retrieval_queries': plan.retrievalQueries,
        'embedding': plan.embedding,
        'search_policy': plan.searchPolicy,
        'hits': hits,
      };
      validateAnalysisContext(context);
      publish(
        'context_frozen',
        mode == 'none'
            ? 'Frozen analysis context has no retrieval hits.'
            : 'Frozen analysis context contains ${hits.length} local retrieval hits.',
      );

      cancellation?.checkpoint();
      final messages = database.transcript(
        revision.id,
        limit: revision.messages,
      );
      if (messages.length != revision.messages) {
        throw StateError(
          'Selected revision message count changed while building the request',
        );
      }
      final workingCorpus = <String, dynamic>{
        'scope_id': _scopeId(corpus.id, revision),
        'messages': messages
            .map(
              (message) => {
                'message_id': message.id,
                'thread_id': message.threadId,
                'timestamp': message.timestamp,
                'sender': message.sender,
                'text': message.body,
              },
            )
            .toList(),
      };
      final payload = <String, dynamic>{
        'question': normalizedQuestion,
        'working_corpus': workingCorpus,
        'analysis_context': context,
      };
      publish(
        'analysis_started',
        'Submitting all ${messages.length} selected-revision messages for analysis.',
      );
      Map<String, dynamic>? completedResult;
      await for (final event in workspace.gateway.conversationalAnalysis(
        payload,
        cancellation: cancellation,
      )) {
        cancellation?.checkpoint();
        publish(event.event, _eventMessage(event), event: event);
        if (event.event == 'failed') {
          throw _gatewayErrorFromEvent(event);
        }
        if (event.event == 'completed') {
          completedResult = event.result;
        }
      }
      final result = completedResult;
      if (result == null) {
        throw GatewayValidationError(
          'Conversation stream completed without a result',
        );
      }
      validateConversationResult(result);
      final presentedAnswer = formatConversationResult(result);
      _ensureScopeStillSelected(corpus, revision);
      database.persistConversation(
        revisionId: revision.id,
        indexGeneration: revision.generation!,
        scopeHash: revision.scopeHash,
        prompt: normalizedQuestion,
        presentedAnswer: presentedAnswer,
        mode: mode,
        result: result,
      );
      publish('persisted', 'Completed answer and visible history were saved.');
      return ConversationExecutionResult(
        question: normalizedQuestion,
        result: result,
        presentedAnswer: presentedAnswer,
        mode: mode,
        progress: List.unmodifiable(progress),
      );
    } finally {
      stopwatch.stop();
      lease.release();
    }
  }

  Future<List<Map<String, dynamic>>> _retrieveSemanticHits(
    EvwDatabase database,
    RevisionSummary revision,
    AnalysisPlanContract plan, {
    required RequestCancellation? cancellation,
    required void Function(String, String, {ServerEvent? event}) publish,
  }) async {
    final embedding = plan.embedding;
    if (embedding == null) {
      throw GatewayValidationError(
        'Semantic analysis plan did not provide embedding geometry',
      );
    }
    final geometry = database.embeddingGeometry(
      revisionId: revision.id,
      indexGeneration: revision.generation!,
    );
    final dimensions = embedding['dimensions'] as int;
    final normalization = embedding['normalization'] as String;
    if (dimensions != geometry.dimensions ||
        normalization != geometry.normalization) {
      throw GatewayError(
        'Embedding geometry does not match the selected local cache',
        code: 'EMBEDDING_CACHE_GEOMETRY_MISMATCH',
        details: {
          'local_dimensions': geometry.dimensions,
          'server_dimensions': dimensions,
          'local_normalization': geometry.normalization,
          'server_normalization': normalization,
        },
      );
    }

    final items = plan.retrievalQueries
        .map(
          (query) => {
            'message_id': query['query_id'] as String,
            'text': query['text'] as String,
          },
        )
        .toList();
    publish(
      'embedding_started',
      'Requesting embeddings for all ${items.length} planner queries in one workload.',
    );
    final vectors = <String, List<double>>{};
    Map<String, dynamic>? accepted;
    Map<String, dynamic>? completed;
    await for (final event in workspace.gateway.embeddings(
      items,
      cancellation: cancellation,
    )) {
      cancellation?.checkpoint();
      publish(event.event, _eventMessage(event), event: event);
      if (event.event == 'failed') throw _gatewayErrorFromEvent(event);
      if (event.event == 'accepted') {
        if (accepted != null) {
          throw GatewayValidationError(
            'Embedding stream emitted duplicate accepted events',
          );
        }
        accepted = event.data;
        _validateAcceptedEmbedding(accepted, embedding, geometry, items.length);
      } else if (event.event == 'vector_batch') {
        if (accepted == null) {
          throw GatewayValidationError(
            'Embedding vectors arrived before accepted event',
          );
        }
        for (final item in (event.data['items'] as List)) {
          final value = (item as Map).cast<String, dynamic>();
          final id = value['message_id'];
          final vector = value['vector'];
          if (id is! String ||
              !items.any((entry) => entry['message_id'] == id)) {
            throw GatewayValidationError(
              'Embedding stream returned an unknown query ID',
            );
          }
          if (vector is! List ||
              vector.length != geometry.dimensions ||
              vector.any((number) => number is! num || !number.isFinite)) {
            throw GatewayValidationError(
              'Embedding vector geometry is invalid',
            );
          }
          if (vectors.containsKey(id)) {
            throw GatewayValidationError(
              'Embedding stream returned a duplicate query vector',
            );
          }
          vectors[id] = vector
              .map((number) => (number as num).toDouble())
              .toList();
        }
      } else if (event.event == 'completed') {
        completed = event.result;
      }
    }
    if (accepted == null || completed == null) {
      throw GatewayValidationError(
        'Embedding stream ended without accepted and completed events',
      );
    }
    if (completed['total_items'] != items.length ||
        completed['embedding_profile_id'] !=
            embedding['embedding_profile_id'] ||
        vectors.length != items.length ||
        !items.every((item) => vectors.containsKey(item['message_id']))) {
      throw GatewayValidationError(
        'Embedding stream did not return exactly one vector for every planner query',
      );
    }

    final hits = <Map<String, dynamic>>[];
    for (final query in items) {
      cancellation?.checkpoint();
      final queryId = query['message_id'] as String;
      final localHits = database.vectorSearch(
        revisionId: revision.id,
        indexGeneration: revision.generation!,
        queryVector: vectors[queryId]!,
        topK: plan.searchPolicy['top_k_per_query'] as int,
      );
      for (var index = 0; index < localHits.length; index++) {
        final hit = localHits[index];
        hits.add({
          'query_id': queryId,
          'message_id': hit.messageId,
          'rank': index + 1,
          'distance': hit.distance,
        });
      }
    }
    if (hits.isEmpty) {
      throw GatewayError(
        'Local embedding search returned no candidates for a semantic plan',
        code: 'RETRIEVAL_EMPTY',
      );
    }
    return hits;
  }

  void _validateAcceptedEmbedding(
    Map<String, dynamic> accepted,
    Map<String, dynamic> expected,
    EmbeddingGeometry local,
    int itemCount,
  ) {
    if (accepted['total_items'] != itemCount ||
        accepted['embedding_profile_id'] != expected['embedding_profile_id'] ||
        accepted['artifact_fingerprint'] != expected['artifact_fingerprint'] ||
        accepted['dimensions'] != local.dimensions ||
        accepted['normalization'] != local.normalization) {
      throw GatewayError(
        'Embedding workload geometry does not match the frozen analysis plan',
        code: 'EMBEDDING_CACHE_GEOMETRY_MISMATCH',
        details: {'accepted': accepted, 'expected': expected},
      );
    }
  }

  void _ensureScopeStillSelected(
    CorpusSummary corpus,
    RevisionSummary revision,
  ) {
    if (workspace.selectedCorpus?.id != corpus.id ||
        workspace.selectedRevision?.id != revision.id ||
        workspace.selectedRevision?.scopeHash != revision.scopeHash) {
      throw StateError(
        'Selected working-corpus scope changed before persistence',
      );
    }
  }

  static String _scopeId(int corpusId, RevisionSummary revision) =>
      'evw15:$corpusId:${revision.id}:${revision.generation}:${revision.scopeHash}';

  static String _eventMessage(ServerEvent event) {
    if (event.event == 'failed') return event.error['message'] as String;
    if (event.event == 'completed') return 'Server analysis completed.';
    final data = event.data;
    return switch (event.event) {
      'accepted' =>
        data['endpoint'] == '/v1/embeddings'
            ? 'Server accepted ${data['total_items']} embedding item(s).'
            : 'Server accepted ${data['message_count']} messages for analysis.',
      'queued' =>
        'Server queued ${data['operation']} behind ${data['queued_count']} request(s).',
      'retry_wait' =>
        'Attempt ${data['failed_attempt']} failed; retry ${data['next_attempt']} starts after ${data['delay_ms']} ms.',
      'heartbeat' =>
        'Server is working: ${data['completed_windows']}/${data['window_count']} windows complete, ${data['active_windows']} active.',
      'accounting_completed' =>
        'Server selected ${data['strategy']} for ${data['corpus_tokens']} corpus tokens.',
      'analysis_plan_accepted' =>
        'Analysis plan accepted with ${data['concept_count']} concepts.',
      'retrieval_suggestions_built' =>
        'Built ${data['suggestion_range_count']} retrieval suggestion ranges.',
      'window_plan_created' =>
        'Planned ${data['window_count']} balanced analysis window(s).',
      'window_started' =>
        'Window ${(data['window_index'] as int) + 1}/${data['window_count']} started.',
      'window_completed' =>
        'Window ${(data['window_index'] as int) + 1}/${data['window_count']} completed with ${data['accepted_range_count']} accepted range(s).',
      'evidence_validation_completed' =>
        'Evidence validation completed: ${data['usable_window_count']}/${data['planned_window_count']} windows usable.',
      'ledger_built' =>
        'Built an evidence ledger with ${data['evidence_range_count']} range(s).',
      'ledger_synthesis_preflight' =>
        data['direct_fit'] == true
            ? 'The complete evidence ledger fits the synthesis call.'
            : 'The evidence ledger exceeds the synthesis context.',
      'ledger_compaction_required' =>
        'Ledger compaction is required and will be logged completely.',
      'ledger_compaction_group_started' =>
        'Ledger compaction group ${(data['group_index'] as int) + 1}/${data['group_count']} started.',
      'ledger_compaction_group_completed' =>
        'Ledger compaction group ${(data['group_index'] as int) + 1}/${data['group_count']} completed.',
      'ledger_compaction_level_completed' =>
        'Ledger compaction level ${data['level']} completed.',
      'ledger_compaction_completed' =>
        'Ledger compaction completed after ${data['group_calls']} group call(s).',
      'ledger_synthesis_started' =>
        'Synthesizing ${data['evidence_range_count']} evidence range(s).',
      'ledger_synthesis_received' =>
        'Synthesis response received for ${data['evidence_range_count']} evidence range(s).',
      'synthesis_validation_completed' =>
        'Synthesis validation completed with status ${data['status']}.',
      'warning' => 'Server warning ${data['code']} at ${data['stage']}.',
      'window_output_unusable' =>
        'Window ${(data['window_index'] as int) + 1}/${data['window_count']} returned unusable output on attempt ${data['attempt']}.',
      'window_unavailable' =>
        'Window ${(data['window_index'] as int) + 1}/${data['window_count']} is unavailable after ${data['attempts']} attempt(s).',
      'retrieval_overlap_completed' =>
        'Retrieval overlap accounting completed.',
      'embedding_batch_started' =>
        'Embedding batch ${(data['batch_index'] as int) + 1}/${data['batch_count']} started.',
      'embedding_progress' =>
        'Embedded ${data['completed_items']}/${data['total_items']} item(s) at ${data['server_items_per_second']} items/second.',
      'vector_batch' =>
        'Received embedding batch ${(data['batch_index'] as int) + 1}.',
      _ => throw StateError('No progress label exists for ${event.event}'),
    };
  }

  static GatewayError _gatewayErrorFromEvent(ServerEvent event) {
    final error = event.error;
    return GatewayError(
      error['message'] as String,
      code: error['code'] as String,
      requestId: error['request_id'] as String,
      stage: error['stage'] as String,
      retryable: error['retryable'] as bool,
      details: (error['details'] as Map).cast<String, dynamic>(),
    );
  }
}

String formatConversationResult(Map<String, dynamic> result) {
  final lines = <String>[];
  final overview = result['overview'];
  final rawAnswer = result['raw_answer'];
  if (overview is String && overview.isNotEmpty) {
    lines.add(overview);
  } else if (rawAnswer is String && rawAnswer.isNotEmpty) {
    lines.add(rawAnswer);
  } else {
    lines.add('The server did not provide a synthesized answer.');
  }
  final results = result['results'];
  if (results is List && results.isNotEmpty) {
    lines.add('');
    lines.add('Findings');
    for (final item in results) {
      if (item is! Map) continue;
      final statement = item['statement'];
      if (statement is String && statement.isNotEmpty) {
        lines.add('• $statement');
      }
    }
  }
  final unclassified = result['unclassified_evidence'];
  if (unclassified is List && unclassified.isNotEmpty) {
    lines.add('');
    lines.add('Unclassified evidence');
    lines.addAll(unclassified.map((item) => '• $item'));
  }
  final unverified = result['unverified_model_statements'];
  if (unverified is List && unverified.isNotEmpty) {
    lines.add('');
    lines.add('Unverified model statements');
    lines.addAll(unverified.map((item) => '• $item'));
  }
  lines.add('');
  lines.add('Complete server result');
  lines.add(const JsonEncoder.withIndent('  ').convert(result));
  return lines.join('\n');
}
