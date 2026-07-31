import 'dart:io';

import 'package:flutter/foundation.dart';

import 'evw_database.dart';
import 'evw_models.dart';
import 'server_gateway.dart';
import 'transcript_editor.dart';

class WorkspaceOperationLease {
  WorkspaceOperationLease._(this._owner, this.label);

  final WorkspaceController _owner;
  final String label;
  bool _released = false;

  bool get released => _released;

  void release() {
    if (_released) return;
    _released = true;
    _owner.endRemoteOperation(this);
  }
}

class WorkspaceController extends ChangeNotifier {
  WorkspaceController({required this.gateway});

  final ServerGateway gateway;
  EvwDatabase? database;
  String? path;
  String? error;
  List<CorpusSummary> corpora = const [];
  CorpusSummary? selectedCorpus;
  RevisionSummary? selectedRevision;
  TranscriptDocumentController? transcriptController;
  int evidenceDataVersion = 0;
  WorkspaceOperationLease? _remoteOperation;
  bool _disposed = false;

  bool get isOpen => database != null;
  bool get hasReadyScope => database != null && selectedRevision != null;
  bool get remoteOperationActive => _remoteOperation != null;
  String? get remoteOperationLabel => _remoteOperation?.label;

  Future<void> open(String requestedPath) async {
    _ensureUsable();
    _refuseWhileRemote('open another EVW');
    final absolute = File(requestedPath).absolute.path;
    if (path == absolute && database != null) return;

    _closeCurrent();
    EvwDatabase? next;
    try {
      next = EvwDatabase.open(absolute);
      final nextCorpora = next.corpora();
      final nextRevisions = next.revisions();
      // Deliberately do not select the first corpus or revision.
      _setDatabase(next, absolute, nextCorpora, nextRevisions);
      next = null;
    } catch (exception) {
      next?.close();
      _clearScope();
      path = null;
      error = '$exception';
      notifyListeners();
    }
  }

  void refresh() {
    _ensureUsable();
    final current = database;
    if (current == null) return;
    final currentCorpusId = selectedCorpus?.id;
    final currentRevisionId = selectedRevision?.id;
    corpora = current.corpora();
    final revisions = current.revisions();
    selectedCorpus = currentCorpusId == null
        ? null
        : corpora.where((item) => item.id == currentCorpusId).firstOrNull;
    if (currentRevisionId != null &&
        revisions.any((item) => item.id == currentRevisionId)) {
      selectedRevision = revisions.firstWhere(
        (item) => item.id == currentRevisionId,
      );
    }
    notifyListeners();
  }

  void close() {
    _ensureUsable();
    _refuseWhileRemote('close the EVW');
    _closeCurrent();
    error = null;
    notifyListeners();
  }

  void selectCorpus(int corpusId) {
    _ensureUsable();
    _refuseWhileRemote('switch working corpus');
    final current = database;
    if (current == null)
      throw StateError('Open an EVW before selecting a corpus');
    final corpus = corpora.where((item) => item.id == corpusId).firstOrNull;
    if (corpus == null)
      throw StateError('Working corpus $corpusId does not exist');
    selectedCorpus = corpus;
    final revisionId = corpus.currentRevisionId;
    if (revisionId == null) {
      _clearScope(keepCorpus: true);
      error = 'Working corpus "${corpus.name}" has no current revision.';
      notifyListeners();
      return;
    }
    final revision = current
        .revisions()
        .where((item) => item.id == revisionId)
        .firstOrNull;
    if (revision == null) {
      _clearScope(keepCorpus: true);
      error = 'Current revision $revisionId is missing.';
      notifyListeners();
      return;
    }
    if (revision.status != 'ready') {
      _clearScope(keepCorpus: true);
      error =
          'Current revision ${revision.number} is ${revision.status}; only ready revisions are usable.';
      notifyListeners();
      return;
    }
    _clearControllerOnly();
    selectedRevision = revision;
    transcriptController = TranscriptDocumentController(
      database: current,
      revision: revision,
      onEvidenceMutation: reportEvidenceMutation,
    )..reload();
    error = null;
    notifyListeners();
  }

  WorkspaceOperationLease beginRemoteOperation(String label) {
    _ensureUsable();
    if (_remoteOperation != null) {
      throw StateError(
        'Cannot start "$label" while "${_remoteOperation!.label}" is active.',
      );
    }
    final lease = WorkspaceOperationLease._(this, label);
    _remoteOperation = lease;
    notifyListeners();
    return lease;
  }

  void endRemoteOperation(WorkspaceOperationLease lease) {
    if (identical(_remoteOperation, lease)) {
      _remoteOperation = null;
      if (!_disposed) notifyListeners();
    }
  }

  void reportEvidenceMutation() {
    evidenceDataVersion += 1;
    if (!_disposed) notifyListeners();
  }

  void _setDatabase(
    EvwDatabase next,
    String absolute,
    List<CorpusSummary> nextCorpora,
    List<RevisionSummary> nextRevisions,
  ) {
    database = next;
    path = absolute;
    corpora = nextCorpora;
    selectedCorpus = null;
    selectedRevision = null;
    transcriptController = null;
    error = null;
    notifyListeners();
  }

  void _closeCurrent() {
    _clearControllerOnly();
    final current = database;
    database = null;
    path = null;
    corpora = const [];
    selectedCorpus = null;
    selectedRevision = null;
    if (current != null) current.close();
  }

  void _clearScope({bool keepCorpus = false}) {
    _clearControllerOnly();
    selectedRevision = null;
    if (!keepCorpus) selectedCorpus = null;
  }

  void _clearControllerOnly() {
    final current = transcriptController;
    transcriptController = null;
    current?.dispose();
  }

  void _refuseWhileRemote(String action) {
    if (_remoteOperation != null) {
      throw StateError(
        'Cannot $action while "${_remoteOperation!.label}" is active. Cancel or wait for it to finish.',
      );
    }
  }

  void _ensureUsable() {
    if (_disposed) throw StateError('Workspace controller is disposed');
  }

  @override
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _remoteOperation = null;
    _clearControllerOnly();
    final current = database;
    database = null;
    if (current != null) current.close();
    super.dispose();
  }
}

extension<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
