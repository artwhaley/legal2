import 'server_contracts.dart';
import 'server_gateway.dart';
import 'evw_models.dart';
import 'workspace_controller.dart';

class EmbeddingSearchWorkflow {
  EmbeddingSearchWorkflow(this.workspace);

  final WorkspaceController workspace;

  Future<List<SearchHit>> execute(
    String query, {
    required int topK,
    RequestCancellation? cancellation,
  }) async {
    if (query.trim().isEmpty)
      throw ArgumentError('Embedding search requires a query');
    if (topK < 1 || topK > 1000)
      throw ArgumentError('Top results must be between 1 and 1000');
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null || revision.generation == null) {
      throw StateError(
        'Select a ready working corpus with an index generation first',
      );
    }
    final localGeometry = database.embeddingGeometry(
      revisionId: revision.id,
      indexGeneration: revision.generation!,
    );
    final lease = workspace.beginRemoteOperation('embedding search');
    try {
      cancellation?.checkpoint();
      final events = workspace.gateway.embeddings([
        {'message_id': 'query', 'text': query},
      ], cancellation: cancellation);
      ServerEvent? accepted;
      List<double>? vector;
      var terminalCount = 0;
      await for (final event in events) {
        if (event.event == 'accepted') {
          if (accepted != null)
            throw GatewayValidationError('Duplicate embedding acceptance');
          accepted = event;
          final data = event.data;
          if (data['total_items'] != 1 ||
              data['dimensions'] != localGeometry.dimensions ||
              data['normalization'] != localGeometry.normalization) {
            throw StateError('EMBEDDING_CACHE_GEOMETRY_MISMATCH');
          }
        } else if (event.event == 'vector_batch') {
          for (final raw in (event.data['items'] as List)) {
            final item = (raw as Map).cast<String, dynamic>();
            if (item['message_id'] != 'query' || vector != null) {
              throw GatewayValidationError(
                'Query embedding stream returned an invalid identity',
              );
            }
            final values = (item['vector'] as List)
                .map((value) => (value as num).toDouble())
                .toList();
            if (values.length != localGeometry.dimensions ||
                values.any((value) => !value.isFinite)) {
              throw StateError('EMBEDDING_CACHE_GEOMETRY_MISMATCH');
            }
            vector = values;
          }
        } else if (event.event == 'completed') {
          terminalCount += 1;
          if (event.result['total_items'] != 1) {
            throw GatewayValidationError(
              'Query embedding terminal count is invalid',
            );
          }
        } else if (event.event == 'failed') {
          final error = event.error;
          throw GatewayError(
            error['message'] as String,
            code: error['code'] as String,
            requestId: error['request_id'] as String,
            stage: error['stage'] as String,
            retryable: error['retryable'] as bool,
            details: (error['details'] as Map).cast<String, dynamic>(),
          );
        }
      }
      if (accepted == null || vector == null || terminalCount != 1) {
        throw GatewayValidationError(
          'Query embedding stream did not return one vector and one completion',
        );
      }
      return database.vectorSearch(
        revisionId: revision.id,
        indexGeneration: revision.generation!,
        queryVector: vector,
        topK: topK,
      );
    } finally {
      lease.release();
    }
  }
}
