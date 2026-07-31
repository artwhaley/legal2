import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'server_contracts.dart';

class RequestCancellation {
  bool _cancelled = false;
  void Function()? _closer;

  bool get cancelled => _cancelled;

  void cancel() {
    _cancelled = true;
    _closer?.call();
  }

  void bind(void Function() closer) {
    _closer = closer;
    if (_cancelled) {
      closer();
      throw GatewayError('Request cancelled by user', cancelled: true);
    }
  }

  void unbind() => _closer = null;

  void checkpoint() {
    if (_cancelled) {
      throw GatewayError('Request cancelled by user', cancelled: true);
    }
  }
}

abstract interface class ServerGateway {
  const ServerGateway();

  String get baseUrl;

  Future<AnalysisPlanContract> conversationalPlan(
    String question, {
    RequestCancellation? cancellation,
  });

  Stream<ServerEvent> embeddings(
    List<Map<String, String>> items, {
    RequestCancellation? cancellation,
  });

  Stream<ServerEvent> conversationalAnalysis(
    Map<String, dynamic> payload, {
    RequestCancellation? cancellation,
  });
}

class UnconfiguredServerGateway implements ServerGateway {
  const UnconfiguredServerGateway({this.baseUrl = 'http://127.0.0.1:8710'});

  @override
  final String baseUrl;

  @override
  Future<AnalysisPlanContract> conversationalPlan(
    String question, {
    RequestCancellation? cancellation,
  }) => Future.error(
    GatewayError('No server gateway is configured for this operation'),
  );

  @override
  Stream<ServerEvent> embeddings(
    List<Map<String, String>> items, {
    RequestCancellation? cancellation,
  }) async* {
    throw GatewayError('No server gateway is configured for this operation');
  }

  @override
  Stream<ServerEvent> conversationalAnalysis(
    Map<String, dynamic> payload, {
    RequestCancellation? cancellation,
  }) async* {
    throw GatewayError('No server gateway is configured for this operation');
  }
}

class HttpServerGateway implements ServerGateway {
  HttpServerGateway(String url, {this.timeout = const Duration(seconds: 120)})
    : baseUrl = _validateBaseUrl(url),
      _client = HttpClient() {
    if (timeout <= Duration.zero)
      throw ArgumentError('Gateway timeout must be positive');
    _client.connectionTimeout = timeout;
  }

  @override
  final String baseUrl;
  final Duration timeout;
  final HttpClient _client;

  @override
  Future<AnalysisPlanContract> conversationalPlan(
    String question, {
    RequestCancellation? cancellation,
  }) async {
    if (question.trim().isEmpty)
      throw ArgumentError('Question cannot be blank');
    final requestId = newRequestId();
    final result = await _postJson('/v1/conversational-plan', {
      'request_id': requestId,
      'question': question,
    }, cancellation: cancellation);
    validateAnalysisPlan(result);
    if (result['request_id'] != requestId) {
      throw GatewayValidationError(
        'Server changed the analysis-plan request identity',
      );
    }
    return AnalysisPlanContract(result);
  }

  @override
  Stream<ServerEvent> embeddings(
    List<Map<String, String>> items, {
    RequestCancellation? cancellation,
  }) => _stream('/v1/embeddings', {
    'request_id': newRequestId(),
    'items': items,
  }, cancellation: cancellation);

  @override
  Stream<ServerEvent> conversationalAnalysis(
    Map<String, dynamic> payload, {
    RequestCancellation? cancellation,
  }) {
    final body = <String, dynamic>{...payload};
    body.putIfAbsent('request_id', newRequestId);
    return _stream(
      '/v1/conversational-analysis',
      body,
      cancellation: cancellation,
    );
  }

  Future<Map<String, dynamic>> _postJson(
    String path,
    Map<String, dynamic> payload, {
    RequestCancellation? cancellation,
  }) async {
    try {
      cancellation?.checkpoint();
      final request = await _openRequest(
        path,
        payload,
        accept: 'application/json',
      ).timeout(timeout);
      cancellation?.bind(request.abort);
      final response = await request.close().timeout(timeout);
      final body = await utf8.decoder.bind(response).join().timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw _parseHttpError(response.statusCode, body);
      }
      _requireContentType(response, 'application/json');
      final value = _decodeObject(body, 'JSON response');
      return value;
    } on GatewayError {
      rethrow;
    } on TimeoutException catch (error) {
      if (cancellation?.cancelled == true)
        throw GatewayError('Request cancelled by user', cancelled: true);
      throw GatewayError(
        'Server request timed out',
        details: {'cause': '$error'},
      );
    } on SocketException catch (error) {
      if (cancellation?.cancelled == true)
        throw GatewayError('Request cancelled by user', cancelled: true);
      throw GatewayError(
        'Server connection failed',
        details: {'cause': '$error'},
      );
    } on HttpException catch (error) {
      if (cancellation?.cancelled == true) {
        throw GatewayError('Request cancelled by user', cancelled: true);
      }
      throw GatewayError('Server request failed', details: {'cause': '$error'});
    } finally {
      cancellation?.unbind();
    }
  }

  Stream<ServerEvent> _stream(
    String path,
    Map<String, dynamic> payload, {
    RequestCancellation? cancellation,
  }) async* {
    final requestId = payload['request_id'] as String;
    var expectedSequence = 1;
    int? configVersion;
    var terminalSeen = false;
    try {
      cancellation?.checkpoint();
      final request = await _openRequest(
        path,
        payload,
        accept: 'application/x-ndjson',
      ).timeout(timeout);
      cancellation?.bind(request.abort);
      final response = await request.close().timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final body = await utf8.decoder.bind(response).join().timeout(timeout);
        throw _parseHttpError(response.statusCode, body);
      }
      _requireContentType(response, 'application/x-ndjson');
      await for (final line
          in response
              .transform(utf8.decoder)
              .transform(const LineSplitter())
              .timeout(timeout)) {
        cancellation?.checkpoint();
        if (line.trim().isEmpty) continue;
        if (terminalSeen)
          throw GatewayValidationError(
            'Server emitted data after its terminal event',
          );
        final raw = jsonDecode(line);
        final event = validateStreamEvent(
          raw,
          endpoint: path,
          expectedRequestId: requestId,
          expectedSequence: expectedSequence,
        );
        if (configVersion == null) {
          configVersion = event.configVersion;
        } else if (event.configVersion != configVersion) {
          throw GatewayValidationError(
            'Server changed configuration version during a stream',
          );
        }
        expectedSequence += 1;
        if (event.terminal) terminalSeen = true;
        yield event;
      }
      if (!terminalSeen)
        throw GatewayValidationError(
          'Server stream ended before a terminal event',
        );
    } on GatewayError {
      rethrow;
    } on GatewayValidationError {
      rethrow;
    } on TimeoutException catch (error) {
      if (cancellation?.cancelled == true)
        throw GatewayError('Request cancelled by user', cancelled: true);
      throw GatewayError(
        'Server stream timed out',
        details: {'cause': '$error'},
      );
    } on SocketException catch (error) {
      if (cancellation?.cancelled == true)
        throw GatewayError('Request cancelled by user', cancelled: true);
      throw GatewayError(
        'Server stream connection failed',
        details: {'cause': '$error'},
      );
    } on FormatException catch (error) {
      throw GatewayValidationError(
        'Server stream returned malformed JSON: $error',
      );
    } on HttpException catch (error) {
      if (cancellation?.cancelled == true) {
        throw GatewayError('Request cancelled by user', cancelled: true);
      }
      throw GatewayError('Server stream failed', details: {'cause': '$error'});
    } finally {
      cancellation?.unbind();
    }
  }

  Future<HttpClientRequest> _openRequest(
    String path,
    Map<String, dynamic> payload, {
    required String accept,
  }) async {
    final request = await _client.postUrl(Uri.parse('$baseUrl$path'));
    request.headers.contentType = ContentType.json;
    request.headers.set(HttpHeaders.acceptHeader, accept);
    request.write(jsonEncode(payload));
    return request;
  }

  static void _requireContentType(
    HttpClientResponse response,
    String expected,
  ) {
    if (response.headers.contentType?.mimeType != expected) {
      throw GatewayValidationError(
        'Server response content type must be $expected, got ${response.headers.contentType?.mimeType ?? 'missing'}',
      );
    }
  }

  static Map<String, dynamic> _decodeObject(String body, String label) {
    final raw = jsonDecode(body);
    if (raw is! Map)
      throw GatewayValidationError('$label must be a JSON object');
    return raw.cast<String, dynamic>();
  }

  static GatewayError _parseHttpError(int statusCode, String body) {
    try {
      final value = _decodeObject(body, 'error response');
      if (!value.keys.toSet().containsAll({
            'request_id',
            'code',
            'message',
            'stage',
            'retryable',
            'details',
          }) ||
          value['message'] is! String ||
          value['code'] is! String ||
          value['stage'] is! String ||
          value['retryable'] is! bool ||
          value['details'] is! Map) {
        throw const FormatException('invalid error fields');
      }
      return GatewayError(
        value['message'] as String,
        statusCode: statusCode,
        code: value['code'] as String,
        requestId: value['request_id'] as String?,
        stage: value['stage'] as String,
        retryable: value['retryable'] as bool,
        details: (value['details'] as Map).cast<String, dynamic>(),
      );
    } catch (_) {
      return GatewayError(
        'Server HTTP $statusCode returned an invalid structured error',
        statusCode: statusCode,
      );
    }
  }

  static String _validateBaseUrl(String value) {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        !{'http', 'https'}.contains(uri.scheme) ||
        uri.host.isEmpty) {
      throw ArgumentError(
        'Server URL must be an absolute http:// or https:// URL',
      );
    }
    return value.replaceFirst(RegExp(r'/+$'), '');
  }

  void close() => _client.close(force: true);
}
