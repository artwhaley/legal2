import 'dart:math';

const conversationEvents = <String>{
  'accepted',
  'queued',
  'retry_wait',
  'heartbeat',
  'accounting_completed',
  'analysis_plan_accepted',
  'retrieval_suggestions_built',
  'window_plan_created',
  'window_started',
  'window_completed',
  'evidence_validation_completed',
  'ledger_built',
  'ledger_synthesis_preflight',
  'ledger_compaction_required',
  'ledger_compaction_group_started',
  'ledger_compaction_group_completed',
  'ledger_compaction_level_completed',
  'ledger_compaction_completed',
  'ledger_synthesis_started',
  'ledger_synthesis_received',
  'synthesis_validation_completed',
  'warning',
  'window_output_unusable',
  'window_unavailable',
  'retrieval_overlap_completed',
  'completed',
  'failed',
};

const embeddingEvents = <String>{
  'accepted',
  'queued',
  'embedding_batch_started',
  'vector_batch',
  'embedding_progress',
  'completed',
  'failed',
};

class GatewayValidationError implements Exception {
  GatewayValidationError(this.message);

  final String message;

  @override
  String toString() => 'GatewayValidationError: $message';
}

class GatewayError implements Exception {
  GatewayError(
    this.message, {
    this.statusCode,
    this.code,
    this.requestId,
    this.stage,
    this.retryable = false,
    this.details = const {},
    this.cancelled = false,
  });

  final String message;
  final int? statusCode;
  final String? code;
  final String? requestId;
  final String? stage;
  final bool retryable;
  final Map<String, dynamic> details;
  final bool cancelled;

  @override
  String toString() =>
      cancelled ? 'CANCELLED: $message' : 'GatewayError: $message';
}

class ServerEvent {
  const ServerEvent(this.value);

  final Map<String, dynamic> value;

  String get event => value['event'] as String;
  int get sequence => value['sequence'] as int;
  int get configVersion => value['config_version'] as int;
  bool get terminal => event == 'completed' || event == 'failed';
  Map<String, dynamic> get data =>
      (value['data'] as Map).cast<String, dynamic>();
  Map<String, dynamic> get result =>
      (value['result'] as Map).cast<String, dynamic>();
  Map<String, dynamic> get error =>
      (value['error'] as Map).cast<String, dynamic>();
}

class AnalysisPlanContract {
  const AnalysisPlanContract(this.value);

  final Map<String, dynamic> value;

  String get requestId => value['request_id'] as String;
  int get configVersion => value['config_version'] as int;
  String get planId => value['analysis_plan_id'] as String;
  Map<String, dynamic> get analysisPlan =>
      (value['analysis_plan'] as Map).cast<String, dynamic>();
  List<Map<String, dynamic>> get retrievalQueries =>
      (value['retrieval_queries'] as List)
          .map((item) => (item as Map).cast<String, dynamic>())
          .toList();
  Map<String, dynamic> get searchPolicy =>
      (value['search_policy'] as Map).cast<String, dynamic>();
  Map<String, dynamic>? get embedding => value['embedding'] == null
      ? null
      : (value['embedding'] as Map).cast<String, dynamic>();
}

void validateAnalysisPlan(Object? raw) {
  final value = _map(raw, 'analysis plan');
  _exact(value, {
    'request_id',
    'config_version',
    'analysis_plan_id',
    'compatibility_fingerprint',
    'analysis_plan',
    'retrieval_queries',
    'embedding',
    'search_policy',
    'usage',
  }, 'analysis plan');
  _uuid(value['request_id'], 'request_id');
  _positiveInt(value['config_version'], 'config_version');
  _uuid(value['analysis_plan_id'], 'analysis_plan_id');
  _fingerprint(value['compatibility_fingerprint'], 'compatibility_fingerprint');
  _validatePlanBody(value['analysis_plan']);
  final queries = _list(value['retrieval_queries'], 'retrieval_queries');
  if (queries.isEmpty || queries.length > 20)
    throw GatewayValidationError('retrieval query count is invalid');
  final queryIds = <String>{};
  final queryTexts = <String>{};
  for (final item in queries) {
    final query = _map(item, 'retrieval query');
    _exact(query, {'query_id', 'text'}, 'retrieval query');
    final id = _trimmedString(query['query_id'], 'retrieval query ID', 512);
    final text = _trimmedString(query['text'], 'retrieval query text', 512);
    if (!queryIds.add(id) || !queryTexts.add(text.toLowerCase())) {
      throw GatewayValidationError('retrieval queries must be unique');
    }
  }
  final policy = _map(value['search_policy'], 'search policy');
  _exact(policy, {
    'mode',
    'top_k_per_query',
    'fusion_method',
    'rrf_constant',
    'maximum_prompt_suggestion_messages',
  }, 'search policy');
  if (policy['mode'] != 'none' && policy['mode'] != 'semantic_ranges' ||
      policy['fusion_method'] != 'reciprocal_rank_fusion') {
    throw GatewayValidationError('search policy is invalid');
  }
  _boundedInt(policy['top_k_per_query'], 'top_k_per_query', 1, 1000);
  _boundedInt(policy['rrf_constant'], 'rrf_constant', 1, 1000);
  _boundedInt(
    policy['maximum_prompt_suggestion_messages'],
    'maximum_prompt_suggestion_messages',
    1,
    500,
  );
  _validateEmbedding(
    value['embedding'],
    required: policy['mode'] == 'semantic_ranges',
  );
  if (policy['mode'] == 'none' && value['embedding'] != null) {
    throw GatewayValidationError('none analysis plan must have null embedding');
  }
  _validateUsage(value['usage'], 'analysis plan usage');
}

void validateAnalysisContext(Object? raw) {
  final value = _map(raw, 'analysis context');
  _exact(value, {
    'analysis_plan_id',
    'plan_config_version',
    'compatibility_fingerprint',
    'analysis_plan',
    'retrieval_queries',
    'embedding',
    'search_policy',
    'hits',
  }, 'analysis context');
  _uuid(value['analysis_plan_id'], 'analysis_plan_id');
  _positiveInt(value['plan_config_version'], 'plan_config_version');
  _fingerprint(value['compatibility_fingerprint'], 'compatibility_fingerprint');
  _validatePlanBody(value['analysis_plan']);
  final queries = _list(value['retrieval_queries'], 'retrieval queries');
  final queryIds = <String>{};
  for (final item in queries) {
    final query = _map(item, 'retrieval query');
    _exact(query, {'query_id', 'text'}, 'retrieval query');
    queryIds.add(_trimmedString(query['query_id'], 'query ID', 512));
  }
  final policy = _map(value['search_policy'], 'search policy');
  _exact(policy, {
    'mode',
    'top_k_per_query',
    'fusion_method',
    'rrf_constant',
    'maximum_prompt_suggestion_messages',
  }, 'search policy');
  final embedding = value['embedding'];
  _validateEmbedding(embedding, required: policy['mode'] == 'semantic_ranges');
  final hits = _list(value['hits'], 'analysis hits');
  final pairs = <String>{};
  final ranks = <String, List<int>>{};
  for (final item in hits) {
    final hit = _map(item, 'retrieval hit');
    _exact(hit, {
      'query_id',
      'message_id',
      'rank',
      'distance',
    }, 'retrieval hit');
    final queryId = _trimmedString(hit['query_id'], 'hit query ID', 512);
    final messageId = _trimmedString(hit['message_id'], 'hit message ID', 512);
    _positiveInt(hit['rank'], 'hit rank');
    _finiteNumber(hit['distance'], 'hit distance', nonnegative: true);
    if (!queryIds.contains(queryId) || !pairs.add('$queryId\u0000$messageId')) {
      throw GatewayValidationError('analysis hit identity is invalid');
    }
    ranks.putIfAbsent(queryId, () => []).add(hit['rank'] as int);
  }
  for (final entry in ranks.entries) {
    final sorted = [...entry.value]..sort();
    for (var index = 0; index < sorted.length; index++) {
      if (sorted[index] != index + 1)
        throw GatewayValidationError(
          'ranks for ${entry.key} are not contiguous',
        );
    }
  }
  if (policy['mode'] == 'none' && (embedding != null || hits.isNotEmpty)) {
    throw GatewayValidationError('none analysis context must be empty');
  }
  if (policy['mode'] == 'semantic_ranges' && hits.isEmpty) {
    throw GatewayValidationError('semantic analysis context requires hits');
  }
}

ServerEvent validateStreamEvent(
  Object? raw, {
  required String endpoint,
  String? expectedRequestId,
  int? expectedSequence,
}) {
  final value = _map(raw, 'stream event');
  final event = value['event'];
  final allowed = endpoint == '/v1/conversational-analysis'
      ? conversationEvents
      : endpoint == '/v1/embeddings'
      ? embeddingEvents
      : <String>{};
  if (event is! String || !allowed.contains(event)) {
    throw GatewayValidationError('event is invalid for $endpoint');
  }
  final payloadKey = event == 'failed'
      ? 'error'
      : event == 'completed'
      ? 'result'
      : 'data';
  _exact(value, {
    'request_id',
    'sequence',
    'event',
    'timestamp',
    'config_version',
    payloadKey,
  }, 'event envelope');
  _uuid(value['request_id'], 'event request_id');
  if (expectedRequestId != null && value['request_id'] != expectedRequestId) {
    throw GatewayValidationError('stream changed request identity');
  }
  _positiveInt(value['sequence'], 'event sequence');
  if (expectedSequence != null && value['sequence'] != expectedSequence) {
    throw GatewayValidationError('stream sequence is not strictly increasing');
  }
  _rfc3339Timestamp(value['timestamp'], 'event timestamp');
  _positiveInt(value['config_version'], 'event config_version');
  if (event == 'failed') {
    final error = _map(value[payloadKey], 'failed error');
    _exact(error, {
      'request_id',
      'code',
      'message',
      'stage',
      'retryable',
      'details',
    }, 'failed error');
    if (error['request_id'] != value['request_id'] ||
        error['code'] is! String ||
        (error['code'] as String).isEmpty ||
        error['message'] is! String ||
        (error['message'] as String).isEmpty ||
        error['stage'] is! String ||
        (error['stage'] as String).isEmpty ||
        error['retryable'] is! bool ||
        error['details'] is! Map) {
      throw GatewayValidationError('failed error is invalid');
    }
  } else if (event == 'accepted') {
    final data = _map(value['data'], 'accepted data');
    if (endpoint == '/v1/embeddings') {
      _exact(data, {
        'endpoint',
        'total_items',
        'embedding_profile_id',
        'model',
        'requested_revision',
        'artifact_fingerprint',
        'dimensions',
        'normalization',
      }, 'embedding accepted data');
      if (data['endpoint'] != endpoint)
        throw GatewayValidationError('embedding endpoint identity changed');
      _positiveInt(data['total_items'], 'embedding total_items');
      _trimmedString(data['embedding_profile_id'], 'embedding profile', 512);
      _trimmedString(data['model'], 'embedding model', 512);
      if (data['requested_revision'] is! String ||
          (data['requested_revision'] as String).length > 512) {
        throw GatewayValidationError('embedding requested revision is invalid');
      }
      _fingerprint(
        data['artifact_fingerprint'],
        'embedding artifact fingerprint',
      );
      _positiveInt(data['dimensions'], 'embedding dimensions');
      if (data['normalization'] != 'unit_l2' &&
          data['normalization'] != 'none') {
        throw GatewayValidationError('embedding normalization is invalid');
      }
    } else {
      _exact(data, {
        'endpoint',
        'scope_id',
        'message_count',
      }, 'conversation accepted data');
      if (data['endpoint'] != endpoint)
        throw GatewayValidationError('conversation endpoint identity changed');
      _trimmedString(data['scope_id'], 'scope_id', 512);
      _positiveInt(data['message_count'], 'message_count');
    }
  } else if (event == 'vector_batch') {
    final data = _map(value['data'], 'vector batch');
    _exact(data, {'batch_index', 'items'}, 'vector batch');
    _nonnegativeInt(data['batch_index'], 'batch_index');
    final items = _list(data['items'], 'vector items');
    if (items.isEmpty) throw GatewayValidationError('vector batch is empty');
    for (final item in items) {
      final vector = _map(item, 'vector item');
      _exact(vector, {'message_id', 'vector'}, 'vector item');
      _trimmedString(vector['message_id'], 'vector message ID', 512);
      final numbers = _list(vector['vector'], 'vector');
      if (numbers.isEmpty ||
          numbers.any((number) => number is! num || !number.isFinite)) {
        throw GatewayValidationError('vector contains a nonfinite value');
      }
    }
  } else if (event == 'completed') {
    final result = _map(value['result'], 'completed result');
    if (endpoint == '/v1/embeddings') {
      _exact(result, {
        'total_items',
        'embedding_profile_id',
      }, 'embedding completed result');
      _positiveInt(result['total_items'], 'embedding completed total_items');
      _trimmedString(
        result['embedding_profile_id'],
        'embedding completed profile',
        512,
      );
    } else {
      validateConversationResult(result);
    }
  } else {
    _validateProgressEvent(event, _map(value['data'], '$event data'));
  }
  return ServerEvent(value);
}

void _validateProgressEvent(String event, Map<String, dynamic> data) {
  if (event == 'queued' || event == 'retry_wait') {
    final required = event == 'queued'
        ? {'operation', 'queued_count', 'wait_timeout_ms'}
        : {
            'operation',
            'failed_attempt',
            'next_attempt',
            'delay_ms',
            'error_code',
          };
    const optional = {'window_id', 'window_index', 'window_count'};
    final keys = data.keys.toSet();
    final optionalPresent = keys.intersection(optional);
    if (!required.difference(keys).isEmpty ||
        !keys.difference(required.union(optional)).isEmpty ||
        optionalPresent.isNotEmpty && !setEquals(optionalPresent, optional)) {
      throw GatewayValidationError(
        '$event data fields do not match the exact contract',
      );
    }
    _trimmedString(data['operation'], '$event operation', 512);
    if (event == 'queued') {
      _nonnegativeInt(data['queued_count'], 'queued count');
      _nonnegativeInt(data['wait_timeout_ms'], 'queue wait timeout');
    } else {
      _positiveInt(data['failed_attempt'], 'failed attempt');
      _positiveInt(data['next_attempt'], 'next attempt');
      _nonnegativeInt(data['delay_ms'], 'retry delay');
      _trimmedString(data['error_code'], 'retry error code', 512);
      if ((data['next_attempt'] as int) <= (data['failed_attempt'] as int)) {
        throw GatewayValidationError('retry attempts are not increasing');
      }
    }
    if (optionalPresent.isNotEmpty) {
      _trimmedString(data['window_id'], '$event window ID', 512);
      _nonnegativeInt(data['window_index'], '$event window index');
      _positiveInt(data['window_count'], '$event window count');
    }
    return;
  }
  if (event == 'heartbeat') {
    _exact(data, {
      'operation',
      'elapsed_ms',
      'completed_windows',
      'active_windows',
      'window_count',
    }, event);
    _trimmedString(data['operation'], 'heartbeat operation', 512);
    _nonnegativeFields(data, {
      'elapsed_ms',
      'completed_windows',
      'active_windows',
      'window_count',
    }, event);
    return;
  }
  if (event == 'accounting_completed') {
    _exact(data, {
      'corpus_tokens',
      'analysis_input_tokens',
      'context_window_tokens',
      'reserved_output_tokens',
      'safety_margin_tokens',
      'strategy',
    }, event);
    _nonnegativeFields(data, {
      'corpus_tokens',
      'analysis_input_tokens',
      'reserved_output_tokens',
      'safety_margin_tokens',
    }, event);
    _positiveInt(data['context_window_tokens'], 'context window tokens');
    if (!{
      'single_window_ledger',
      'multi_window_ledger',
    }.contains(data['strategy'])) {
      throw GatewayValidationError('accounting strategy is invalid');
    }
    return;
  }
  if (event == 'analysis_plan_accepted') {
    _exact(data, {
      'analysis_plan_id',
      'compatibility_fingerprint',
      'concept_count',
      'retrieval_query_count',
      'retrieval_mode',
    }, event);
    _uuid(data['analysis_plan_id'], 'accepted analysis plan ID');
    _fingerprint(
      data['compatibility_fingerprint'],
      'accepted compatibility fingerprint',
    );
    _positiveInt(data['concept_count'], 'accepted concept count');
    _positiveInt(data['retrieval_query_count'], 'accepted retrieval count');
    if (!{'none', 'semantic_ranges'}.contains(data['retrieval_mode'])) {
      throw GatewayValidationError('accepted retrieval mode is invalid');
    }
    return;
  }
  if (event == 'retrieval_suggestions_built') {
    _exact(data, {
      'unique_candidate_message_count',
      'selected_suggestion_message_count',
      'suggestion_range_count',
      'unselected_candidate_message_count',
    }, event);
    _nonnegativeFields(data, data.keys.toSet(), event);
    return;
  }
  if (event == 'window_plan_created') {
    _exact(data, {
      'strategy',
      'window_count',
      'message_count',
      'hard_input_tokens',
      'target_input_tokens',
      'utilization_percent',
      'retrieval_reserve_tokens',
      'window_plan_hash',
    }, event);
    if (!{
      'single_window_ledger',
      'multi_window_ledger',
    }.contains(data['strategy'])) {
      throw GatewayValidationError('window plan strategy is invalid');
    }
    for (final key in {
      'window_count',
      'message_count',
      'hard_input_tokens',
      'target_input_tokens',
    }) {
      _positiveInt(data[key], 'window plan $key');
    }
    _nonnegativeInt(
      data['retrieval_reserve_tokens'],
      'window plan retrieval reserve',
    );
    _finiteNumber(data['utilization_percent'], 'window utilization');
    final utilization = (data['utilization_percent'] as num).toDouble();
    if (utilization < 1 || utilization > 100) {
      throw GatewayValidationError('window utilization is outside its bounds');
    }
    _fingerprint(data['window_plan_hash'], 'window plan hash');
    return;
  }
  if (event == 'window_started') {
    _exact(data, {
      'window_id',
      'window_index',
      'window_count',
      'message_count',
      'suggestion_range_count',
    }, event);
    _trimmedString(data['window_id'], 'window ID', 512);
    _nonnegativeInt(data['window_index'], 'window index');
    _positiveInt(data['window_count'], 'window count');
    _positiveInt(data['message_count'], 'window message count');
    _nonnegativeInt(data['suggestion_range_count'], 'suggestion range count');
    return;
  }
  if (event == 'window_completed') {
    _exact(data, {
      'window_id',
      'window_index',
      'window_count',
      'accepted_range_count',
      'rejected_range_count',
      'normalized_range_count',
      'validation_status',
      'input_tokens',
      'output_tokens',
      'usage_source',
      'estimated_cost',
      'accepted_ranges',
      'window_uncertainties',
    }, event);
    _trimmedString(data['window_id'], 'completed window ID', 512);
    _nonnegativeInt(data['window_index'], 'completed window index');
    _positiveInt(data['window_count'], 'completed window count');
    _nonnegativeFields(data, {
      'accepted_range_count',
      'rejected_range_count',
      'normalized_range_count',
      'input_tokens',
      'output_tokens',
    }, event);
    final expectedStatus = data['rejected_range_count'] == 0
        ? 'complete'
        : 'partial';
    if (data['validation_status'] != expectedStatus ||
        (data['normalized_range_count'] as int) >
            (data['accepted_range_count'] as int) ||
        !{'provider_reported', 'estimated'}.contains(data['usage_source'])) {
      throw GatewayValidationError('completed window data is inconsistent');
    }
    final acceptedRanges = _list(data['accepted_ranges'], 'accepted ranges');
    if (acceptedRanges.length != data['accepted_range_count']) {
      throw GatewayValidationError('accepted range count is inconsistent');
    }
    final sourceIndexes = <int>[];
    for (final rawRange in acceptedRanges) {
      final range = _map(rawRange, 'accepted range');
      _exact(range, {
        'source_range_index',
        'thread_id',
        'start_message_id',
        'end_message_id',
        'summary',
        'relevance',
        'normalizations',
      }, 'accepted range');
      _nonnegativeInt(
        range['source_range_index'],
        'accepted range source index',
      );
      sourceIndexes.add(range['source_range_index'] as int);
      _trimmedString(range['thread_id'], 'accepted range thread ID', 512);
      _trimmedString(range['start_message_id'], 'accepted range start ID', 512);
      _trimmedString(range['end_message_id'], 'accepted range end ID', 512);
      _nullableText(range['summary'], 'accepted range summary');
      _nullableText(range['relevance'], 'accepted range relevance');
      final normalizations = _list(
        range['normalizations'],
        'accepted range normalizations',
      );
      if (normalizations.any((value) => value != 'endpoint_order_swapped')) {
        throw GatewayValidationError('accepted range normalization is invalid');
      }
    }
    if (sourceIndexes.toSet().length != sourceIndexes.length ||
        !_isSorted(sourceIndexes)) {
      throw GatewayValidationError(
        'accepted range source indexes are unordered',
      );
    }
    for (final uncertainty in _list(
      data['window_uncertainties'],
      'window uncertainties',
    )) {
      _trimmedString(uncertainty, 'window uncertainty', 20000);
    }
    _nullableNonnegativeNumber(data['estimated_cost'], 'window cost');
    return;
  }
  if (event == 'evidence_validation_completed') {
    _exact(data, {
      'planned_window_count',
      'usable_window_count',
      'unavailable_window_count',
      'accepted_range_count',
      'rejected_range_count',
      'normalized_range_count',
      'status',
    }, event);
    _nonnegativeFields(data, data.keys.toSet()..remove('status'), event);
    final expectedStatus =
        data['rejected_range_count'] != 0 ||
            data['unavailable_window_count'] != 0
        ? 'partial'
        : 'complete';
    if ((data['usable_window_count'] as int) +
                (data['unavailable_window_count'] as int) !=
            data['planned_window_count'] ||
        data['status'] != expectedStatus ||
        (data['normalized_range_count'] as int) >
            (data['accepted_range_count'] as int)) {
      throw GatewayValidationError('evidence validation event is inconsistent');
    }
    return;
  }
  if (event == 'ledger_built') {
    _exact(data, {'window_count', 'evidence_range_count'}, event);
    _positiveInt(data['window_count'], 'ledger window count');
    _nonnegativeInt(data['evidence_range_count'], 'ledger evidence count');
    return;
  }
  if (event == 'ledger_synthesis_preflight') {
    _validateSynthesisPreflight(data, event, includeMaximumDepth: false);
    return;
  }
  if (event.startsWith('ledger_compaction_')) {
    _validateCompactionEvent(event, data);
    return;
  }
  if (event == 'ledger_synthesis_started') {
    _exact(data, {'evidence_range_count'}, event);
    _nonnegativeInt(data['evidence_range_count'], 'synthesis evidence count');
    return;
  }
  if (event == 'ledger_synthesis_received') {
    _exact(data, {
      'evidence_range_count',
      'content_nonblank',
      'input_tokens',
      'output_tokens',
      'usage_source',
      'estimated_cost',
    }, event);
    _nonnegativeFields(data, {
      'evidence_range_count',
      'input_tokens',
      'output_tokens',
    }, event);
    if (data['content_nonblank'] is! bool ||
        !{'provider_reported', 'estimated'}.contains(data['usage_source'])) {
      throw GatewayValidationError('synthesis receipt data is invalid');
    }
    _nullableNonnegativeNumber(data['estimated_cost'], 'synthesis cost');
    return;
  }
  if (event == 'synthesis_validation_completed') {
    _exact(data, {
      'status',
      'result_count',
      'verified_citation_count',
      'unverified_citation_count',
      'omitted_range_count',
      'warning_count',
    }, event);
    _nonnegativeFields(data, data.keys.toSet()..remove('status'), event);
    if (!{
      'conformant',
      'warnings',
      'unparseable',
      'unavailable',
    }.contains(data['status'])) {
      throw GatewayValidationError('synthesis validation status is invalid');
    }
    return;
  }
  if (event == 'warning') {
    _exact(data, {'code', 'details', 'stage', 'operation', 'window_id'}, event);
    _trimmedString(data['code'], 'warning code', 512);
    if (data['details'] is! Map) {
      throw GatewayValidationError('warning details must be an object');
    }
    _trimmedString(data['stage'], 'warning stage', 512);
    _nullableBoundedString(data['operation'], 'warning operation');
    _nullableBoundedString(data['window_id'], 'warning window ID');
    return;
  }
  if (event == 'window_output_unusable' || event == 'window_unavailable') {
    final attemptsKey = event == 'window_output_unusable'
        ? 'attempt'
        : 'attempts';
    _exact(data, {
      'window_id',
      'window_index',
      'window_count',
      attemptsKey,
      'code',
    }, event);
    _trimmedString(data['window_id'], '$event window ID', 512);
    _trimmedString(data['code'], '$event code', 512);
    _nonnegativeInt(data['window_index'], '$event window index');
    _positiveInt(data['window_count'], '$event window count');
    if (event == 'window_output_unusable') {
      _positiveInt(data[attemptsKey], '$event attempt');
    } else {
      _nonnegativeInt(data[attemptsKey], '$event attempts');
    }
    return;
  }
  if (event == 'retrieval_overlap_completed') {
    _exact(data, {
      'final_ranges_overlapping_suggestions',
      'final_ranges_outside_suggestions',
      'answer_relevant_ranges_overlapping_suggestions',
      'answer_relevant_ranges_outside_suggestions',
      'suggestions_without_final_evidence',
    }, event);
    _nonnegativeFields(data, data.keys.toSet(), event);
    return;
  }
  if (event == 'embedding_batch_started') {
    _exact(data, {
      'batch_index',
      'batch_count',
      'first_item_index',
      'last_item_index',
      'item_count',
    }, event);
    _nonnegativeInt(data['batch_index'], 'embedding batch index');
    _positiveInt(data['batch_count'], 'embedding batch count');
    _nonnegativeInt(data['first_item_index'], 'embedding first item');
    _nonnegativeInt(data['last_item_index'], 'embedding last item');
    _positiveInt(data['item_count'], 'embedding item count');
    if ((data['last_item_index'] as int) < (data['first_item_index'] as int) ||
        data['item_count'] !=
            (data['last_item_index'] as int) -
                (data['first_item_index'] as int) +
                1) {
      throw GatewayValidationError('embedding batch bounds are inconsistent');
    }
    return;
  }
  if (event == 'embedding_progress') {
    _exact(data, {
      'completed_items',
      'total_items',
      'server_items_per_second',
    }, event);
    _nonnegativeInt(data['completed_items'], 'completed embedding items');
    _positiveInt(data['total_items'], 'total embedding items');
    _finiteNumber(
      data['server_items_per_second'],
      'embedding items per second',
      nonnegative: true,
    );
    if ((data['completed_items'] as int) > (data['total_items'] as int)) {
      throw GatewayValidationError(
        'completed embedding items exceed total items',
      );
    }
    return;
  }
  throw GatewayValidationError('No payload validator exists for $event');
}

void _validateSynthesisPreflight(
  Map<String, dynamic> data,
  String event, {
  required bool includeMaximumDepth,
}) {
  final keys = {
    'evidence_range_count',
    'evidence_message_count',
    'required_input_tokens',
    'usable_input_tokens',
    'excess_input_tokens',
    'direct_fit',
    if (includeMaximumDepth) 'maximum_depth',
  };
  _exact(data, keys, event);
  _nonnegativeFields(
    data,
    keys.difference({'direct_fit', 'maximum_depth'}),
    event,
  );
  if (data['direct_fit'] is! bool) {
    throw GatewayValidationError('$event direct_fit must be boolean');
  }
  if (includeMaximumDepth) {
    _positiveInt(data['maximum_depth'], '$event maximum depth');
  }
}

void _validateCompactionEvent(String event, Map<String, dynamic> data) {
  if (event == 'ledger_compaction_required') {
    _validateSynthesisPreflight(data, event, includeMaximumDepth: true);
    return;
  }
  if (event == 'ledger_compaction_group_started' ||
      event == 'ledger_compaction_group_completed') {
    final keys = {
      'level',
      'group_id',
      'group_index',
      'group_count',
      'covered_range_count',
      if (event == 'ledger_compaction_group_completed') ...{
        'input_tokens',
        'output_tokens',
        'usage_source',
        'estimated_cost',
      },
    };
    _exact(data, keys, event);
    _positiveInt(data['level'], '$event level');
    _trimmedString(data['group_id'], '$event group ID', 512);
    _nonnegativeInt(data['group_index'], '$event group index');
    _positiveInt(data['group_count'], '$event group count');
    _nonnegativeInt(data['covered_range_count'], '$event covered ranges');
    if (event == 'ledger_compaction_group_completed') {
      _nonnegativeInt(data['input_tokens'], '$event input tokens');
      _nonnegativeInt(data['output_tokens'], '$event output tokens');
      if (!{'provider_reported', 'estimated'}.contains(data['usage_source'])) {
        throw GatewayValidationError('$event usage source is invalid');
      }
      _nullableNonnegativeNumber(data['estimated_cost'], '$event cost');
    }
    return;
  }
  if (event == 'ledger_compaction_level_completed') {
    _exact(data, {'level', 'group_count', 'covered_range_count'}, event);
    _positiveInt(data['level'], '$event level');
    _positiveInt(data['group_count'], '$event group count');
    _nonnegativeInt(data['covered_range_count'], '$event covered ranges');
    return;
  }
  if (event == 'ledger_compaction_completed') {
    _exact(data, {
      'levels',
      'group_calls',
      'original_range_count',
      'covered_range_count',
      'final_synthesis_input_tokens',
    }, event);
    _positiveInt(data['levels'], '$event levels');
    _positiveInt(data['group_calls'], '$event group calls');
    _nonnegativeFields(data, {
      'original_range_count',
      'covered_range_count',
      'final_synthesis_input_tokens',
    }, event);
    return;
  }
  throw GatewayValidationError('Unknown compaction event $event');
}

void _nonnegativeFields(
  Map<String, dynamic> data,
  Set<String> keys,
  String label,
) {
  for (final key in keys) {
    _nonnegativeInt(data[key], '$label $key');
  }
}

void _nullableNonnegativeNumber(Object? value, String label) {
  if (value != null) _finiteNumber(value, label, nonnegative: true);
}

void _nullableBoundedString(Object? value, String label) {
  if (value != null) _trimmedString(value, label, 512);
}

void validateConversationResult(Map<String, dynamic> result) {
  _exact(result, {
    'completion_status',
    'answer_source',
    'overview',
    'raw_answer',
    'results',
    'unclassified_evidence',
    'unverified_model_statements',
    'evidence_ledger',
    'evidence_validation',
    'synthesis_validation',
    'coverage',
    'retrieval_diagnostics',
    'ledger_processing',
    'usage',
    'uncertainties',
    'strategy',
  }, 'conversation result');
  if (!{
        'complete',
        'complete_with_warnings',
        'partial',
      }.contains(result['completion_status']) ||
      !{
        'structured_synthesis',
        'raw_synthesis_output',
        'synthesis_unavailable',
      }.contains(result['answer_source'])) {
    throw GatewayValidationError('conversation result status is invalid');
  }
  if (result['answer_source'] == 'structured_synthesis' &&
      (result['overview'] is! String ||
          (result['overview'] as String).isEmpty ||
          result['raw_answer'] != null)) {
    throw GatewayValidationError('structured result text is invalid');
  }
  if (result['answer_source'] == 'raw_synthesis_output' &&
      (result['raw_answer'] is! String ||
          (result['raw_answer'] as String).isEmpty ||
          result['overview'] != null)) {
    throw GatewayValidationError('raw result text is invalid');
  }
  if (result['answer_source'] == 'synthesis_unavailable' &&
      (result['overview'] != null || result['raw_answer'] != null)) {
    throw GatewayValidationError('unavailable result contains synthesis text');
  }
  if (result['overview'] != null &&
      (result['overview'] is! String ||
          (result['overview'] as String).trim().isEmpty)) {
    throw GatewayValidationError('conversation overview is invalid');
  }
  if (result['raw_answer'] != null &&
      (result['raw_answer'] is! String ||
          (result['raw_answer'] as String).trim().isEmpty)) {
    throw GatewayValidationError('raw conversation answer is invalid');
  }
  final ledger = _list(result['evidence_ledger'], 'evidence ledger');
  final ledgerIds = <String>{};
  for (final item in ledger) {
    final record = _map(item, 'ledger record');
    _exact(record, {
      'range_id',
      'window_id',
      'source_range_index',
      'thread_id',
      'start_message_id',
      'end_message_id',
      'summary',
      'relevance',
      'normalizations',
      'uncertainties',
      'warnings',
    }, 'ledger record');
    final id = _trimmedString(record['range_id'], 'range ID', 512);
    if (!ledgerIds.add(id))
      throw GatewayValidationError('duplicate ledger range ID');
    _trimmedString(record['window_id'], 'window ID', 512);
    _nonnegativeInt(record['source_range_index'], 'source range index');
    _trimmedString(record['thread_id'], 'thread ID', 512);
    _trimmedString(record['start_message_id'], 'start message ID', 512);
    _trimmedString(record['end_message_id'], 'end message ID', 512);
    _nullableText(record['summary'], 'ledger summary');
    _nullableText(record['relevance'], 'ledger relevance');
    _stringList(record['normalizations'], 'ledger normalizations');
    _stringList(record['uncertainties'], 'ledger uncertainties');
    _validateWarnings(record['warnings'], 'ledger warnings');
  }
  for (final item in _list(result['results'], 'public results')) {
    final entry = _map(item, 'public result');
    _exact(entry, {
      'probability',
      'classification_status',
      'statement',
      'reported_range_ids',
      'verified_range_ids',
      'unverified_range_ids',
      'citation_status',
      'uncertainty',
      'warnings',
    }, 'public result');
    if (!{
          'model_classified',
          'unclassified',
        }.contains(entry['classification_status']) ||
        !{
          'verified',
          'partial',
          'unverified',
        }.contains(entry['citation_status']) ||
        entry['statement'] is! String ||
        (entry['statement'] as String).trim().isEmpty ||
        entry['probability'] != null &&
            !{
              'high_probability',
              'lower_probability',
            }.contains(entry['probability']) ||
        entry['uncertainty'] != null && entry['uncertainty'] is! String) {
      throw GatewayValidationError('public result fields are invalid');
    }
    _stringList(entry['reported_range_ids'], 'reported range IDs');
    for (final id in _list(entry['verified_range_ids'], 'verified range IDs')) {
      if (id is! String || !ledgerIds.contains(id))
        throw GatewayValidationError(
          'public result references an unknown verified range',
        );
    }
    _stringList(entry['unverified_range_ids'], 'unverified range IDs');
    _validateWarnings(entry['warnings'], 'public result warnings');
  }
  for (final item in _list(
    result['unclassified_evidence'],
    'unclassified evidence',
  )) {
    final value = _map(item, 'unclassified evidence');
    _exact(value, {
      'range_id',
      'summary',
      'relevance',
      'reason',
    }, 'unclassified evidence');
    _trimmedString(value['range_id'], 'unclassified range ID', 512);
    _nullableText(value['summary'], 'unclassified summary');
    _nullableText(value['relevance'], 'unclassified relevance');
    if (value['reason'] != 'not_referenced_by_synthesis') {
      throw GatewayValidationError('unclassified evidence reason is invalid');
    }
  }
  for (final item in _list(
    result['unverified_model_statements'],
    'unverified model statements',
  )) {
    final value = _map(item, 'unverified model statement');
    _exact(value, {
      'statement',
      'reported_range_ids',
      'probability',
      'uncertainty',
      'warnings',
    }, 'unverified model statement');
    if (value['statement'] is! String ||
        (value['statement'] as String).trim().isEmpty ||
        value['probability'] != null &&
            !{
              'high_probability',
              'lower_probability',
            }.contains(value['probability']) ||
        value['uncertainty'] != null && value['uncertainty'] is! String) {
      throw GatewayValidationError('unverified model statement is invalid');
    }
    _stringList(value['reported_range_ids'], 'unverified reported range IDs');
    _validateWarnings(value['warnings'], 'unverified warnings');
  }
  _validateEvidenceValidation(result['evidence_validation']);
  _validateSynthesisValidation(result['synthesis_validation']);
  _validateCoverage(result['coverage']);
  _validateRetrievalDiagnostics(result['retrieval_diagnostics']);
  _validateLedgerProcessing(result['ledger_processing']);
  _validateUsage(result['usage'], 'conversation usage');
  _stringList(result['uncertainties'], 'conversation uncertainties');
  if (!{
    'single_window_ledger',
    'multi_window_ledger',
  }.contains(result['strategy'])) {
    throw GatewayValidationError('conversation strategy is invalid');
  }
  final evidenceValidation = _map(
    result['evidence_validation'],
    'evidence validation',
  );
  final synthesisValidation = _map(
    result['synthesis_validation'],
    'synthesis validation',
  );
  if (result['completion_status'] == 'complete' &&
      (evidenceValidation['status'] != 'complete' ||
          synthesisValidation['status'] != 'conformant' ||
          (result['unclassified_evidence'] as List).isNotEmpty ||
          (result['unverified_model_statements'] as List).isNotEmpty ||
          (result['results'] as List).any(
            (item) => item is Map && (item['warnings'] as List).isNotEmpty,
          ))) {
    throw GatewayValidationError(
      'complete result contains warnings or partial facts',
    );
  }
}

void _validateEvidenceValidation(Object? raw) {
  final value = _map(raw, 'evidence validation');
  _exact(value, {
    'planned_window_count',
    'usable_window_count',
    'unavailable_window_count',
    'unavailable_windows',
    'status',
    'accepted_range_count',
    'rejected_range_count',
    'normalized_range_count',
    'rejected_ranges',
    'warnings',
  }, 'evidence validation');
  final planned = _nonnegativeIntValue(
    value['planned_window_count'],
    'planned windows',
  );
  final usable = _nonnegativeIntValue(
    value['usable_window_count'],
    'usable windows',
  );
  final unavailable = _nonnegativeIntValue(
    value['unavailable_window_count'],
    'unavailable windows',
  );
  if (usable + unavailable != planned ||
      !{'complete', 'partial'}.contains(value['status'])) {
    throw GatewayValidationError(
      'evidence validation counts/status are invalid',
    );
  }
  final unavailableRows = _list(
    value['unavailable_windows'],
    'unavailable windows',
  );
  if (unavailableRows.length != unavailable) {
    throw GatewayValidationError('unavailable window count is inconsistent');
  }
  for (final item in unavailableRows) {
    final row = _map(item, 'unavailable window');
    _exact(row, {
      'window_id',
      'window_index',
      'window_count',
      'attempts',
      'code',
    }, 'unavailable window');
    _trimmedString(row['window_id'], 'unavailable window ID', 512);
    _nonnegativeInt(row['window_index'], 'unavailable window index');
    _positiveInt(row['window_count'], 'unavailable window count');
    _nonnegativeInt(row['attempts'], 'unavailable attempts');
    _trimmedString(row['code'], 'unavailable code', 512);
  }
  final rejected = _list(value['rejected_ranges'], 'rejected ranges');
  final rejectedCount = _nonnegativeIntValue(
    value['rejected_range_count'],
    'rejected ranges',
  );
  final accepted = _nonnegativeIntValue(
    value['accepted_range_count'],
    'accepted ranges',
  );
  final normalized = _nonnegativeIntValue(
    value['normalized_range_count'],
    'normalized ranges',
  );
  if (rejected.length != rejectedCount || normalized > accepted) {
    throw GatewayValidationError('evidence range counts are inconsistent');
  }
  for (final item in rejected) {
    final row = _map(item, 'rejected range');
    _exact(row, {
      'window_id',
      'range_index',
      'code',
      'message',
      'declared_thread_id',
      'start_message_id',
      'end_message_id',
    }, 'rejected range');
    _trimmedString(row['window_id'], 'rejected range window ID', 512);
    _nonnegativeInt(row['range_index'], 'rejected range index');
    _trimmedString(row['code'], 'rejected range code', 512);
    _trimmedString(row['message'], 'rejected range message', 20000);
    _nullableText(row['declared_thread_id'], 'declared thread ID');
    _nullableText(row['start_message_id'], 'rejected start ID');
    _nullableText(row['end_message_id'], 'rejected end ID');
  }
  _validateWarnings(value['warnings'], 'evidence validation warnings');
  if (value['status'] == 'complete' &&
      (rejectedCount != 0 || unavailable != 0)) {
    throw GatewayValidationError(
      'complete evidence validation has incomplete facts',
    );
  }
}

void _validateSynthesisValidation(Object? raw) {
  final value = _map(raw, 'synthesis validation');
  _exact(value, {
    'status',
    'raw_output_preserved',
    'warnings',
  }, 'synthesis validation');
  if (!{
        'conformant',
        'warnings',
        'unparseable',
        'unavailable',
      }.contains(value['status']) ||
      value['raw_output_preserved'] is! bool) {
    throw GatewayValidationError('synthesis validation is invalid');
  }
  _validateWarnings(value['warnings'], 'synthesis validation warnings');
  if (value['status'] == 'conformant' &&
      (value['warnings'] as List).isNotEmpty) {
    throw GatewayValidationError('conformant synthesis has warnings');
  }
}

void _validateCoverage(Object? raw) {
  final value = _map(raw, 'coverage');
  _exact(value, {
    'message_count',
    'planned_window_count',
    'usable_window_count',
    'unavailable_window_count',
    'evidence_range_count',
  }, 'coverage');
  final planned = _nonnegativeIntValue(
    value['planned_window_count'],
    'coverage planned windows',
  );
  final usable = _nonnegativeIntValue(
    value['usable_window_count'],
    'coverage usable windows',
  );
  final unavailable = _nonnegativeIntValue(
    value['unavailable_window_count'],
    'coverage unavailable windows',
  );
  _nonnegativeInt(value['message_count'], 'coverage messages');
  _nonnegativeInt(value['evidence_range_count'], 'coverage evidence ranges');
  if (usable + unavailable != planned) {
    throw GatewayValidationError('coverage window counts are inconsistent');
  }
}

void _validateRetrievalDiagnostics(Object? raw) {
  final value = _map(raw, 'retrieval diagnostics');
  _exact(value, {
    'mode',
    'query_count',
    'raw_hit_count',
    'unique_candidate_message_count',
    'selected_suggestion_message_count',
    'suggestion_range_count',
    'final_ranges_overlapping_suggestions',
    'final_ranges_outside_suggestions',
    'answer_relevant_ranges_overlapping_suggestions',
    'answer_relevant_ranges_outside_suggestions',
    'suggestions_without_final_evidence',
  }, 'retrieval diagnostics');
  if (!{'none', 'semantic_ranges'}.contains(value['mode'])) {
    throw GatewayValidationError('retrieval diagnostics mode is invalid');
  }
  for (final key in value.keys.where((key) => key != 'mode')) {
    _nonnegativeInt(value[key], 'retrieval diagnostic $key');
  }
}

void _validateLedgerProcessing(Object? raw) {
  final value = _map(raw, 'ledger processing');
  _exact(value, {
    'direct_synthesis_input_tokens',
    'synthesis_usable_input_tokens',
    'compaction_applied',
    'compaction_levels',
    'compaction_group_calls',
  }, 'ledger processing');
  _nonnegativeInt(
    value['direct_synthesis_input_tokens'],
    'direct synthesis tokens',
  );
  _nonnegativeInt(
    value['synthesis_usable_input_tokens'],
    'usable synthesis tokens',
  );
  _nonnegativeInt(value['compaction_levels'], 'compaction levels');
  _nonnegativeInt(value['compaction_group_calls'], 'compaction group calls');
  if (value['compaction_applied'] is! bool) {
    throw GatewayValidationError('compaction applied flag is invalid');
  }
}

void _validateWarnings(Object? raw, String label) {
  for (final item in _list(raw, label)) {
    final warning = _map(item, label);
    _exact(warning, {'code', 'details'}, label);
    _trimmedString(warning['code'], '$label code', 512);
    if (warning['details'] is! Map) {
      throw GatewayValidationError('$label details must be an object');
    }
  }
}

String? _nullableText(Object? value, String label, [int maximum = 20000]) {
  if (value == null) return null;
  if (value is! String || value.trim().isEmpty || value.length > maximum) {
    throw GatewayValidationError('$label is invalid');
  }
  return value;
}

int _nonnegativeIntValue(Object? value, String label) {
  _nonnegativeInt(value, label);
  return value as int;
}

Map<String, dynamic> _map(Object? value, String label) {
  if (value is! Map) throw GatewayValidationError('$label must be an object');
  return value.cast<String, dynamic>();
}

List<dynamic> _list(Object? value, String label) {
  if (value is! List) throw GatewayValidationError('$label must be a list');
  return value;
}

void _exact(Map<String, dynamic> value, Set<String> keys, String label) {
  if (!setEquals(value.keys.toSet(), keys)) {
    throw GatewayValidationError(
      '$label fields do not match the exact contract',
    );
  }
}

void _validatePlanBody(Object? raw) {
  final plan = _map(raw, 'analysis plan');
  _exact(plan, {
    'analysis_question',
    'answer_objective',
    'concepts',
    'inclusion_criteria',
    'exclusion_criteria',
    'answer_requirements',
    'interpretive_assumptions',
  }, 'analysis plan');
  _trimmedString(plan['analysis_question'], 'analysis question', 20000);
  _trimmedString(plan['answer_objective'], 'answer objective', 20000);
  final concepts = _list(plan['concepts'], 'concepts');
  if (concepts.isEmpty || concepts.length > 12)
    throw GatewayValidationError('concept count is invalid');
  for (final item in concepts) {
    final concept = _map(item, 'concept');
    _exact(concept, {'label', 'definition', 'manifestations'}, 'concept');
    _trimmedString(concept['label'], 'concept label', 20000);
    _trimmedString(concept['definition'], 'concept definition', 20000);
    if (_list(concept['manifestations'], 'manifestations').isEmpty)
      throw GatewayValidationError('manifestations are empty');
  }
  _nonemptyStringList(plan['inclusion_criteria'], 'inclusion criteria');
  _stringList(plan['exclusion_criteria'], 'exclusion criteria');
  _nonemptyStringList(plan['answer_requirements'], 'answer requirements');
  _stringList(plan['interpretive_assumptions'], 'interpretive assumptions');
}

void _validateEmbedding(Object? raw, {required bool required}) {
  if (raw == null) {
    if (required)
      throw GatewayValidationError('semantic mode requires embedding metadata');
    return;
  }
  final value = _map(raw, 'embedding metadata');
  _exact(value, {
    'embedding_profile_id',
    'artifact_fingerprint',
    'dimensions',
    'normalization',
  }, 'embedding metadata');
  _trimmedString(value['embedding_profile_id'], 'embedding profile ID', 512);
  _fingerprint(value['artifact_fingerprint'], 'artifact fingerprint');
  _positiveInt(value['dimensions'], 'embedding dimensions');
  if (value['normalization'] != 'unit_l2' && value['normalization'] != 'none')
    throw GatewayValidationError('embedding normalization is invalid');
}

void _validateUsage(Object? raw, String label) {
  final value = _map(raw, label);
  _exact(value, {
    'input_tokens',
    'output_tokens',
    'source',
    'estimated_cost',
    'cost_complete',
    'currency',
  }, label);
  _nonnegativeInt(value['input_tokens'], '$label input tokens');
  _nonnegativeInt(value['output_tokens'], '$label output tokens');
  if (!{'provider_reported', 'estimated', 'mixed'}.contains(value['source']) ||
      value['cost_complete'] is! bool ||
      value['currency'] != 'USD')
    throw GatewayValidationError('$label is invalid');
}

List<String> _stringList(Object? raw, String label) => _list(
  raw,
  label,
).map((item) => _trimmedString(item, label, 20000)).toList();

List<String> _nonemptyStringList(Object? raw, String label) {
  final list = _stringList(raw, label);
  if (list.isEmpty) throw GatewayValidationError('$label cannot be empty');
  return list;
}

String _trimmedString(Object? value, String label, int maximum) {
  if (value is! String ||
      value.isEmpty ||
      value.length > maximum ||
      value != value.trim())
    throw GatewayValidationError('$label is invalid');
  return value;
}

bool _isSorted(List<int> values) {
  for (var index = 1; index < values.length; index++) {
    if (values[index] < values[index - 1]) return false;
  }
  return true;
}

void _positiveInt(Object? value, String label) {
  if (value is! int || value <= 0)
    throw GatewayValidationError('$label must be a positive integer');
}

void _nonnegativeInt(Object? value, String label) {
  if (value is! int || value < 0)
    throw GatewayValidationError('$label must be a nonnegative integer');
}

void _boundedInt(Object? value, String label, int minimum, int maximum) {
  if (value is! int || value < minimum || value > maximum)
    throw GatewayValidationError('$label is outside its bounds');
}

void _finiteNumber(Object? value, String label, {bool nonnegative = false}) {
  if (value is! num || !value.isFinite || nonnegative && value < 0)
    throw GatewayValidationError('$label is invalid');
}

void _uuid(Object? value, String label) {
  final text = _trimmedString(value, label, 512);
  final parts = text.split('-');
  if (parts.length != 5 ||
      parts[0].length != 8 ||
      parts[1].length != 4 ||
      parts[2].length != 4 ||
      parts[3].length != 4 ||
      parts[4].length != 12)
    throw GatewayValidationError('$label is not a UUID');
}

void _rfc3339Timestamp(Object? value, String label) {
  final text = _trimmedString(value, label, 128);
  if (!RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(text) ||
      DateTime.tryParse(text) == null) {
    throw GatewayValidationError('$label must be an RFC 3339 timestamp');
  }
}

void _fingerprint(Object? value, String label) {
  final text = _trimmedString(value, label, 64);
  if (text.length != 64 || !RegExp(r'^[0-9a-f]{64}$').hasMatch(text))
    throw GatewayValidationError('$label is invalid');
}

bool setEquals<T>(Set<T> left, Set<T> right) =>
    left.length == right.length && left.containsAll(right);

String newRequestId() {
  final bytes = List<int>.generate(16, (_) => Random.secure().nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  String hex(int value) => value.toRadixString(16).padLeft(2, '0');
  final text = bytes.map(hex).join();
  return '${text.substring(0, 8)}-${text.substring(8, 12)}-${text.substring(12, 16)}-${text.substring(16, 20)}-${text.substring(20)}';
}
