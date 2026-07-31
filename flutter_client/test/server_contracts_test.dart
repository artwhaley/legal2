import 'package:evw_client/src/server_contracts.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('every nonterminal progress event enforces its exact payload', () {
    final cases = <String, Map<String, dynamic>>{
      'queued': {
        'operation': 'window_scan',
        'queued_count': 1,
        'wait_timeout_ms': 1000,
      },
      'retry_wait': {
        'operation': 'window_scan',
        'failed_attempt': 1,
        'next_attempt': 2,
        'delay_ms': 100,
        'error_code': 'PROVIDER_503',
        'window_id': 'w1',
        'window_index': 0,
        'window_count': 2,
      },
      'heartbeat': {
        'operation': 'window_scan',
        'elapsed_ms': 100,
        'completed_windows': 1,
        'active_windows': 1,
        'window_count': 2,
      },
      'accounting_completed': {
        'corpus_tokens': 100,
        'analysis_input_tokens': 120,
        'context_window_tokens': 1000,
        'reserved_output_tokens': 100,
        'safety_margin_tokens': 50,
        'strategy': 'multi_window_ledger',
      },
      'analysis_plan_accepted': {
        'analysis_plan_id': '22222222-2222-4222-8222-222222222222',
        'compatibility_fingerprint': List.filled(64, 'a').join(),
        'concept_count': 1,
        'retrieval_query_count': 1,
        'retrieval_mode': 'semantic_ranges',
      },
      'retrieval_suggestions_built': {
        'unique_candidate_message_count': 10,
        'selected_suggestion_message_count': 5,
        'suggestion_range_count': 2,
        'unselected_candidate_message_count': 5,
      },
      'window_plan_created': {
        'strategy': 'multi_window_ledger',
        'window_count': 2,
        'message_count': 10,
        'hard_input_tokens': 1000,
        'target_input_tokens': 800,
        'utilization_percent': 80.0,
        'retrieval_reserve_tokens': 50,
        'window_plan_hash': List.filled(64, 'b').join(),
      },
      'window_started': {
        'window_id': 'w1',
        'window_index': 0,
        'window_count': 2,
        'message_count': 5,
        'suggestion_range_count': 1,
      },
      'window_completed': {
        'window_id': 'w1',
        'window_index': 0,
        'window_count': 2,
        'accepted_range_count': 2,
        'rejected_range_count': 0,
        'normalized_range_count': 1,
        'validation_status': 'complete',
        'input_tokens': 100,
        'output_tokens': 20,
        'usage_source': 'provider_reported',
        'estimated_cost': 0.01,
      },
      'evidence_validation_completed': {
        'planned_window_count': 2,
        'usable_window_count': 2,
        'unavailable_window_count': 0,
        'accepted_range_count': 2,
        'rejected_range_count': 0,
        'normalized_range_count': 1,
        'status': 'complete',
      },
      'ledger_built': {'window_count': 2, 'evidence_range_count': 2},
      'ledger_synthesis_preflight': {
        'evidence_range_count': 2,
        'evidence_message_count': 5,
        'required_input_tokens': 200,
        'usable_input_tokens': 1000,
        'excess_input_tokens': 0,
        'direct_fit': true,
      },
      'ledger_compaction_required': {
        'evidence_range_count': 20,
        'evidence_message_count': 50,
        'required_input_tokens': 2000,
        'usable_input_tokens': 1000,
        'excess_input_tokens': 1000,
        'direct_fit': false,
        'maximum_depth': 2,
      },
      'ledger_compaction_group_started': {
        'level': 1,
        'group_id': 'g1',
        'group_index': 0,
        'group_count': 2,
        'covered_range_count': 10,
      },
      'ledger_compaction_group_completed': {
        'level': 1,
        'group_id': 'g1',
        'group_index': 0,
        'group_count': 2,
        'covered_range_count': 10,
        'input_tokens': 200,
        'output_tokens': 40,
        'usage_source': 'estimated',
        'estimated_cost': null,
      },
      'ledger_compaction_level_completed': {
        'level': 1,
        'group_count': 2,
        'covered_range_count': 20,
      },
      'ledger_compaction_completed': {
        'levels': 1,
        'group_calls': 2,
        'original_range_count': 20,
        'covered_range_count': 20,
        'final_synthesis_input_tokens': 500,
      },
      'ledger_synthesis_started': {'evidence_range_count': 2},
      'ledger_synthesis_received': {
        'evidence_range_count': 2,
        'content_nonblank': true,
        'input_tokens': 100,
        'output_tokens': 20,
        'usage_source': 'provider_reported',
        'estimated_cost': 0.01,
      },
      'synthesis_validation_completed': {
        'status': 'conformant',
        'result_count': 2,
        'verified_citation_count': 2,
        'unverified_citation_count': 0,
        'omitted_range_count': 0,
        'warning_count': 0,
      },
      'warning': {
        'code': 'PROVIDER_WARNING',
        'details': <String, dynamic>{},
        'stage': 'window_scan',
        'operation': null,
        'window_id': null,
      },
      'window_output_unusable': {
        'window_id': 'w1',
        'window_index': 0,
        'window_count': 2,
        'attempt': 1,
        'code': 'OUTPUT_INVALID',
      },
      'window_unavailable': {
        'window_id': 'w1',
        'window_index': 0,
        'window_count': 2,
        'attempts': 2,
        'code': 'PROVIDER_FAILED',
      },
      'retrieval_overlap_completed': {
        'final_ranges_overlapping_suggestions': 1,
        'final_ranges_outside_suggestions': 1,
        'answer_relevant_ranges_overlapping_suggestions': 1,
        'answer_relevant_ranges_outside_suggestions': 0,
        'suggestions_without_final_evidence': 1,
      },
      'embedding_batch_started': {
        'batch_index': 0,
        'batch_count': 1,
        'first_item_index': 0,
        'last_item_index': 1,
        'item_count': 2,
      },
      'embedding_progress': {
        'completed_items': 1,
        'total_items': 2,
        'server_items_per_second': 4.5,
      },
    };

    for (final entry in cases.entries) {
      final endpoint =
          entry.key == 'embedding_batch_started' ||
              entry.key == 'embedding_progress'
          ? '/v1/embeddings'
          : '/v1/conversational-analysis';
      expect(
        () => validateStreamEvent(
          _event(entry.key, entry.value),
          endpoint: endpoint,
        ),
        returnsNormally,
        reason: entry.key,
      );
    }
  });

  test('progress validation rejects extra fields and inconsistent totals', () {
    expect(
      () => validateStreamEvent(
        _event('heartbeat', {
          'operation': 'window_scan',
          'elapsed_ms': 100,
          'completed_windows': 1,
          'active_windows': 1,
          'window_count': 2,
          'invented': true,
        }),
        endpoint: '/v1/conversational-analysis',
      ),
      throwsA(isA<GatewayValidationError>()),
    );
    expect(
      () => validateStreamEvent(
        _event('embedding_progress', {
          'completed_items': 3,
          'total_items': 2,
          'server_items_per_second': 1.0,
        }),
        endpoint: '/v1/embeddings',
      ),
      throwsA(isA<GatewayValidationError>()),
    );
  });
}

Map<String, dynamic> _event(String event, Map<String, dynamic> data) => {
  'request_id': '11111111-1111-4111-8111-111111111111',
  'sequence': 1,
  'event': event,
  'timestamp': '2026-01-01T00:00:00Z',
  'config_version': 1,
  'data': data,
};
