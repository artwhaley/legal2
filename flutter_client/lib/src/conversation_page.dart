import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import 'conversation_workflow.dart';
import 'evw_database.dart';
import 'evw_models.dart';
import 'server_contracts.dart';
import 'server_gateway.dart';
import 'transcript_editor.dart';
import 'workstation_widgets.dart';
import 'workspace_controller.dart';

class ConversationPage extends StatefulWidget {
  const ConversationPage({
    super.key,
    required this.workspace,
    required this.isPageActive,
  });

  final WorkspaceController workspace;
  final bool isPageActive;

  @override
  State<ConversationPage> createState() => _ConversationPageState();
}

class _ConversationCard {
  _ConversationCard(this.question) : startedAt = DateTime.now();

  final String question;
  final DateTime startedAt;
  ConversationExecutionResult? outcome;
  Object? failure;
  final List<ConversationProgress> progress = [];
  final List<_ActivityEntry> activity = [];
  final List<_ProvisionalRange> provisionalRanges = [];
  Duration elapsed = Duration.zero;
  bool active = true;
}

class _ActivityEntry {
  const _ActivityEntry({required this.title, this.details = const []});

  final String title;
  final List<String> details;
}

class _ProvisionalRange {
  const _ProvisionalRange({
    required this.windowNumber,
    required this.sourceRangeIndex,
    required this.threadId,
    required this.startMessageId,
    required this.endMessageId,
    required this.summary,
    required this.relevance,
  });

  final int windowNumber;
  final int sourceRangeIndex;
  final String threadId;
  final String startMessageId;
  final String endMessageId;
  final String? summary;
  final String? relevance;
}

class _ConversationPageState extends State<ConversationPage> {
  static const int _defaultSemanticStrength = 40;
  static const int _minimumSemanticStrength = 1;
  static const int _maximumSemanticStrength = 500;

  final TextEditingController _question = TextEditingController();
  final GlobalKey<TranscriptEvidenceEditorState> _editorKey = GlobalKey();
  final List<_ConversationCard> _cards = [];
  RequestCancellation? _cancellation;
  Timer? _progressTimer;
  bool _stopRequested = false;
  int _semanticStrength = _defaultSemanticStrength;
  String? _error;
  String? _notice;
  int? _loadedRevisionId;

  WorkspaceController get workspace => widget.workspace;

  @override
  void initState() {
    super.initState();
    workspace.addListener(_onWorkspaceChanged);
  }

  @override
  void dispose() {
    workspace.removeListener(_onWorkspaceChanged);
    _progressTimer?.cancel();
    _question.dispose();
    super.dispose();
  }

  void _onWorkspaceChanged() {
    final revisionId = workspace.selectedRevision?.id;
    if (revisionId != _loadedRevisionId && _cards.isNotEmpty) {
      _loadedRevisionId = revisionId;
      if (mounted) setState(_cards.clear);
    }
    if (mounted) setState(() {});
  }

  Future<void> _send() async {
    final text = _question.text.trim();
    if (text.isEmpty) {
      setState(() => _error = 'Question cannot be blank.');
      return;
    }
    if (_cancellation != null) return;
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) {
      setState(() => _error = 'Select a ready working corpus on Corpus first.');
      return;
    }
    final card = _ConversationCard(text);
    final cancellation = RequestCancellation();
    _startProgressTimer(card);
    setState(() {
      _error = null;
      _notice = null;
      _cards.add(card);
      _loadedRevisionId = revision.id;
      _cancellation = cancellation;
      _stopRequested = false;
    });
    try {
      final outcome = await ConversationWorkflow(workspace: workspace).run(
        text,
        maximumPromptSuggestionMessages: _semanticStrength,
        cancellation: cancellation,
        onProgress: (item) {
          if (!mounted) return;
          setState(() => _recordProgress(card, item));
        },
      );
      if (mounted) setState(() => card.outcome = outcome);
    } catch (error) {
      if (mounted) {
        setState(() {
          card.failure = error;
          if (error is GatewayError && error.cancelled) {
            _notice = error.toString();
            _error = null;
          } else {
            _error = '$error';
          }
        });
      }
    } finally {
      _finishProgressTimer(card);
      if (mounted) {
        setState(() {
          _cancellation = null;
          _stopRequested = false;
        });
      }
    }
  }

  void _recordProgress(_ConversationCard card, ConversationProgress item) {
    card.progress.add(item);
    final notice = _activityNotice(card, item);
    if (notice != null) card.activity.add(notice);

    final event = item.event;
    if (event?.event != 'window_completed') return;
    final data = _optionalEventData(event!);
    final windowIndex = data?['window_index'];
    if (windowIndex is! int) return;
    final rawRanges = data?['accepted_ranges'];
    if (rawRanges is! List) return;
    for (final raw in rawRanges) {
      if (raw is! Map) continue;
      final range = raw.cast<String, dynamic>();
      final sourceRangeIndex = range['source_range_index'];
      final threadId = range['thread_id'];
      final startMessageId = range['start_message_id'];
      final endMessageId = range['end_message_id'];
      if (sourceRangeIndex is! int ||
          threadId is! String ||
          startMessageId is! String ||
          endMessageId is! String) {
        continue;
      }
      card.provisionalRanges.add(
        _ProvisionalRange(
          windowNumber: windowIndex + 1,
          sourceRangeIndex: sourceRangeIndex,
          threadId: threadId,
          startMessageId: startMessageId,
          endMessageId: endMessageId,
          summary: range['summary'] is String
              ? range['summary'] as String
              : null,
          relevance: range['relevance'] is String
              ? range['relevance'] as String
              : null,
        ),
      );
    }
  }

  _ActivityEntry? _activityNotice(
    _ConversationCard card,
    ConversationProgress item,
  ) {
    if (item.phase == 'planning_started') {
      return const _ActivityEntry(title: 'Formulating Analysis Plan...');
    }
    if (item.phase == 'planning_completed') {
      final details = <String>['User query: ${card.question}'];
      final expanded = item.metadata['analysis_question'];
      if (expanded is String && expanded.trim().isNotEmpty) {
        details.add('Expanded search prompt: $expanded');
      }
      final queries = item.metadata['retrieval_queries'];
      if (queries is List) {
        final terms = queries.whereType<String>().toList();
        if (terms.isNotEmpty) {
          details.add(
            'keywords extracted for preliminary suggestions: ${terms.join(', ')}',
          );
        }
      }
      return _ActivityEntry(title: 'Analysis Plan Ready.', details: details);
    }

    final event = item.event;
    if (event == null) return null;
    final name = event.event;
    final data = _optionalEventData(event);
    if (name == 'retrieval_suggestions_built') {
      final count = data?['selected_suggestion_message_count'];
      if (count is int) {
        return _ActivityEntry(
          title:
              'Flagged $count message${count == 1 ? '' : 's'} as preliminary suggestions for consideration.',
        );
      }
      return null;
    }
    if (name == 'window_plan_created') {
      final count = data?['window_count'];
      if (count is int) {
        return _ActivityEntry(
          title: 'Splitting the working corpus into $count windows.',
        );
      }
      return null;
    }
    if (name == 'window_started') {
      final alreadyStarted = card.activity.any(
        (entry) => entry.title == 'Beginning Analysis...',
      );
      return alreadyStarted
          ? null
          : const _ActivityEntry(title: 'Beginning Analysis...');
    }
    if (name == 'window_completed') {
      final windowIndex = data?['window_index'];
      final windowCount = data?['window_count'];
      if (windowIndex is! int || windowCount is! int) return null;
      final rangeCount = data?['accepted_range_count'];
      final details = rangeCount is int
          ? <String>[
              'Window ${windowIndex + 1} returned $rangeCount candidate message '
                  'range${rangeCount == 1 ? '' : 's'}.',
            ]
          : const <String>[];
      return _ActivityEntry(
        title:
            'Window ${windowIndex + 1} complete of $windowCount total windows.',
        details: details,
      );
    }
    if (name == 'ledger_built') {
      final rangeCount = data?['evidence_range_count'];
      if (rangeCount is int) {
        return _ActivityEntry(
          title:
              'All Windows Complete, passing $rangeCount total evidence ranges for synthesis into final answer.',
        );
      }
      return null;
    }
    if (name == 'completed') {
      return const _ActivityEntry(
        title: 'Synthesis Complete - Displaying final answer.',
      );
    }
    return null;
  }

  Map<String, dynamic>? _optionalEventData(ServerEvent event) {
    final raw = event.value['data'];
    return raw is Map ? raw.cast<String, dynamic>() : null;
  }

  void _startProgressTimer(_ConversationCard card) {
    _progressTimer?.cancel();
    _progressTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted || !card.active) return;
      setState(() {
        card.elapsed = DateTime.now().difference(card.startedAt);
      });
    });
  }

  void _finishProgressTimer(_ConversationCard card) {
    card.elapsed = DateTime.now().difference(card.startedAt);
    card.active = false;
    _progressTimer?.cancel();
    _progressTimer = null;
  }

  void _cancel() {
    if (_cancellation == null || _stopRequested) return;
    _stopRequested = true;
    _cancellation!.cancel();
    if (mounted) {
      setState(() {
        _notice = 'Cancellation requested. Waiting for the request to close.';
        _error = null;
      });
    }
  }

  void _viewRange(Map<String, dynamic> range) {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    final start = range['start_message_id'];
    final end = range['end_message_id'];
    if (database == null ||
        revision == null ||
        start is! String ||
        end is! String) {
      _showRangeFailure('Range endpoints are not valid.');
      return;
    }
    final core = database.coreMessageForRange(revision.id, start, end);
    if (core == null) {
      _showRangeFailure(
        'Range cannot be navigated because its endpoints are absent, cross threads, or out of order.',
      );
      return;
    }
    if (!(_editorKey.currentState?.focusMessage(core.id) ?? false)) {
      _showRangeFailure(
        'The shared transcript editor could not focus this range.',
      );
    }
  }

  void _saveRange(Map<String, dynamic> range, {String? statement}) {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    final start = range['start_message_id'];
    final end = range['end_message_id'];
    if (database == null ||
        revision == null ||
        start is! String ||
        end is! String) {
      _showRangeFailure('Range endpoints are not valid.');
      return;
    }
    final rangeId = range['range_id'];
    final summary = range['summary'] is String
        ? range['summary'] as String
        : range['relevance'] is String
        ? range['relevance'] as String
        : '';
    final title = statement?.trim().isNotEmpty == true
        ? statement!.trim()
        : summary.trim().isNotEmpty
        ? summary.trim()
        : 'Evidence ${rangeId is String ? rangeId : ''}'.trim();
    try {
      final block = database.createConversationalEvidenceBlock(
        revisionId: revision.id,
        startMessageId: start,
        endMessageId: end,
        title: title,
        summary: summary,
      );
      final controller = workspace.transcriptController;
      if (controller == null) {
        throw StateError('The shared transcript controller is unavailable');
      }
      controller.reload();
      controller.selectBlock(block.id);
      if (!(_editorKey.currentState?.focusMessage(block.coreMessageId) ??
          false)) {
        throw StateError(
          'Evidence was saved, but the transcript could not focus its core message',
        );
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Saved evidence block ${block.id}')),
        );
      }
    } catch (error) {
      _showRangeFailure('$error');
    }
  }

  void _showRangeFailure(String message) {
    if (mounted) setState(() => _error = message);
  }

  @override
  Widget build(BuildContext context) {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) {
      return const WorkstationPage(
        title: 'Evidence conversation',
        child: EmptyWorkspaceState(
          icon: Icons.question_answer_outlined,
          title: 'Conversation requires a working corpus',
          message:
              'Select a ready working corpus on Corpus to use Conversation.',
        ),
      );
    }
    return WorkstationPage(
      title: 'Evidence conversation',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            const SizedBox(height: 8),
            OperationalMessage(
              message: _error!,
              label: 'FAILED',
              tone: OperationalTone.failure,
            ),
          ],
          if (_notice != null) ...[
            const SizedBox(height: 8),
            OperationalMessage(message: _notice!),
          ],
          const SizedBox(height: 8),
          Expanded(
            flex: 3,
            child: Card(
              margin: EdgeInsets.zero,
              child: _cards.isEmpty
                  ? const Center(
                      child: Text(
                        'Ask a question about the selected revision.',
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.all(12),
                      itemCount: _cards.length,
                      itemBuilder: (context, index) => _ConversationCardView(
                        card: _cards[index],
                        database: database,
                        revision: revision,
                        onViewRange: _viewRange,
                        onSaveRange: _saveRange,
                      ),
                    ),
            ),
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: TextField(
                  controller: _question,
                  minLines: 1,
                  maxLines: 4,
                  enabled: _cancellation == null,
                  decoration: const InputDecoration(
                    labelText: 'Question',
                    hintText: 'Ask about the selected revision',
                    prefixIcon: Icon(Icons.help_outline, size: 19),
                  ),
                  onSubmitted: (_) => _send(),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                onPressed: _cancellation == null
                    ? _send
                    : (_stopRequested ? null : _cancel),
                icon: Icon(_cancellation == null ? Icons.send : Icons.stop),
                label: Text(
                  _cancellation == null
                      ? 'Send'
                      : (_stopRequested ? 'Stopping...' : 'Stop'),
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: 190,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Semantic Strength',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                    Row(
                      children: [
                        Expanded(
                          child: Slider(
                            min: _minimumSemanticStrength.toDouble(),
                            max: _maximumSemanticStrength.toDouble(),
                            divisions:
                                _maximumSemanticStrength -
                                _minimumSemanticStrength,
                            value: _semanticStrength.toDouble(),
                            label: '$_semanticStrength',
                            onChanged: _cancellation == null
                                ? (value) => setState(
                                    () => _semanticStrength = value.round(),
                                  )
                                : null,
                          ),
                        ),
                        SizedBox(width: 30, child: Text('$_semanticStrength')),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            flex: 4,
            child: TranscriptEvidenceEditor(
              key: _editorKey,
              database: database,
              revision: revision,
              controller: workspace.transcriptController,
              isPageActive: widget.isPageActive,
              sidebarWidth:
                  workspace.splitSize(
                    'flutter.split.transcript_evidence_sidebar',
                  ) ??
                  350,
              onSidebarWidthChanged: (value) => workspace.persistSplitSize(
                'flutter.split.transcript_evidence_sidebar',
                value,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ConversationCardView extends StatelessWidget {
  const _ConversationCardView({
    required this.card,
    required this.database,
    required this.revision,
    required this.onViewRange,
    required this.onSaveRange,
  });

  final _ConversationCard card;
  final EvwDatabase database;
  final RevisionSummary revision;
  final void Function(Map<String, dynamic>) onViewRange;
  final void Function(Map<String, dynamic>, {String? statement}) onSaveRange;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Card(
        color: Theme.of(context).colorScheme.surfaceContainer,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.help_outline,
                size: 18,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'QUESTION',
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        color: Theme.of(context).colorScheme.primary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    SelectableText(card.question),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
      const SizedBox(height: 6),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: _conversationBody(context),
        ),
      ),
      const SizedBox(height: 12),
    ],
  );

  Widget _conversationBody(BuildContext context) {
    if (card.outcome == null) {
      if (card.failure == null) {
        return _WorkingConversationState(
          progress: card.progress,
          activity: card.activity,
          elapsed: card.elapsed,
          provisionalRanges: card.provisionalRanges,
        );
      }
      final cancelled =
          card.failure is GatewayError &&
          (card.failure as GatewayError).cancelled;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SelectableText(
            '${cancelled ? 'CANCELLED' : 'FAILED'}\n${card.failure}',
          ),
          if (card.provisionalRanges.isNotEmpty) ...[
            const SizedBox(height: 12),
            _ProvisionalEvidencePanel(
              ranges: card.provisionalRanges,
              incomplete: true,
            ),
          ],
          if (card.activity.isNotEmpty)
            _ActivityHistory(activity: card.activity),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _RunSummary(card: card, result: card.outcome!.result),
        const SizedBox(height: 8),
        _ResultView(
          result: card.outcome!.result,
          database: database,
          revision: revision,
          onViewRange: onViewRange,
          onSaveRange: onSaveRange,
        ),
        if (card.activity.isNotEmpty) _ActivityHistory(activity: card.activity),
      ],
    );
  }
}

class _WorkingConversationState extends StatelessWidget {
  const _WorkingConversationState({
    required this.progress,
    required this.activity,
    required this.elapsed,
    required this.provisionalRanges,
  });

  final List<ConversationProgress> progress;
  final List<_ActivityEntry> activity;
  final Duration elapsed;
  final List<_ProvisionalRange> provisionalRanges;

  @override
  Widget build(BuildContext context) {
    final latest = activity.isEmpty ? null : activity.last;
    final windowEvents = progress
        .map((item) => item.event)
        .whereType<ServerEvent>()
        // Terminal envelopes carry `result` or `error`, not progress `data`.
        // They can briefly be present in the active card while the workflow's
        // final state is being applied, especially when another widget
        // triggers a rebuild (such as expanding Activity).
        .where((event) => !event.terminal)
        .toList();
    final completedWindows = windowEvents
        .where((event) => event.event == 'window_completed')
        .length;
    final windowCounts = windowEvents
        .map((event) => event.data['window_count'])
        .whereType<int>()
        .toList();
    final windowCount = windowCounts.isEmpty ? null : windowCounts.first;
    final heartbeats = windowEvents
        .where((event) => event.event == 'heartbeat')
        .toList();
    final latestHeartbeat = heartbeats.isEmpty ? null : heartbeats.last;
    final activeWindows = latestHeartbeat?.data['active_windows'];
    final progressValue = windowCount == null || windowCount == 0
        ? null
        : (completedWindows / windowCount).clamp(0.0, 1.0).toDouble();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    latest?.title ?? 'Working',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  if (latest != null && latest.details.isNotEmpty)
                    Text(
                      latest.details.first,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                ],
              ),
            ),
            Text(
              _formatDuration(elapsed),
              style: Theme.of(context).textTheme.labelMedium,
            ),
          ],
        ),
        if (progressValue != null) ...[
          const SizedBox(height: 10),
          LinearProgressIndicator(value: progressValue),
          const SizedBox(height: 5),
          Text(
            '$completedWindows of $windowCount windows completed'
            '${activeWindows is int ? ' · $activeWindows active' : ''}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
        if (provisionalRanges.isNotEmpty) ...[
          const SizedBox(height: 12),
          _ProvisionalEvidencePanel(ranges: provisionalRanges),
        ],
        if (activity.isNotEmpty) ...[
          const SizedBox(height: 8),
          _ActivityHistory(activity: activity),
        ],
      ],
    );
  }
}

class _ProvisionalRangeTile extends StatelessWidget {
  const _ProvisionalRangeTile(this.range);

  final _ProvisionalRange range;

  @override
  Widget build(BuildContext context) => ListTile(
    dense: true,
    contentPadding: EdgeInsets.zero,
    title: Text(
      'Window ${range.windowNumber} · ${range.summary ?? 'Description unavailable'}',
    ),
    subtitle: Text(
      '${range.startMessageId} -> ${range.endMessageId}'
      '${range.relevance == null ? '' : '\n${range.relevance}'}',
    ),
  );
}

class _ProvisionalEvidencePanel extends StatelessWidget {
  const _ProvisionalEvidencePanel({
    required this.ranges,
    this.incomplete = false,
  });

  final List<_ProvisionalRange> ranges;
  final bool incomplete;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text(
        'Preliminary evidence - final synthesis may merge, reclassify, or omit these ranges.'
        '${incomplete ? ' This run is incomplete.' : ''}',
      ),
      const SizedBox(height: 6),
      ...ranges.map(_ProvisionalRangeTile.new),
    ],
  );
}

class _RunSummary extends StatelessWidget {
  const _RunSummary({required this.card, required this.result});

  final _ConversationCard card;
  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final coverage = result['coverage'] is Map
        ? (result['coverage'] as Map).cast<String, dynamic>()
        : const <String, dynamic>{};
    final usable = coverage['usable_window_count'];
    final planned = coverage['planned_window_count'];
    final ranges = coverage['evidence_range_count'];
    final parts = <String>['Completed in ${_formatDuration(card.elapsed)}'];
    if (usable is int && planned is int)
      parts.add('$usable/$planned windows usable');
    if (ranges is int) parts.add('$ranges candidate ranges');
    return Text(
      parts.join(' - '),
      style: Theme.of(context).textTheme.bodySmall,
    );
  }
}

class _ActivityHistory extends StatelessWidget {
  const _ActivityHistory({required this.activity});

  final List<_ActivityEntry> activity;

  @override
  Widget build(BuildContext context) {
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      childrenPadding: EdgeInsets.zero,
      title: Text('Activity (${activity.length} updates)'),
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 280),
          child: ListView.builder(
            primary: false,
            shrinkWrap: true,
            itemCount: activity.length,
            itemBuilder: (context, index) {
              final item = activity[index];
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(item.title),
                    for (final detail in item.details)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(
                          detail,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _ResultView extends StatelessWidget {
  const _ResultView({
    required this.result,
    required this.database,
    required this.revision,
    required this.onViewRange,
    required this.onSaveRange,
  });

  final Map<String, dynamic> result;
  final EvwDatabase database;
  final RevisionSummary revision;
  final void Function(Map<String, dynamic>) onViewRange;
  final void Function(Map<String, dynamic>, {String? statement}) onSaveRange;

  @override
  Widget build(BuildContext context) {
    final ledger =
        (result['evidence_ledger'] as List?)
            ?.whereType<Map>()
            .map((item) => item.cast<String, dynamic>())
            .toList() ??
        const <Map<String, dynamic>>[];
    final knownIds = ledger
        .map((item) => item['range_id'])
        .whereType<String>()
        .toSet();
    final statementByRange = <String, String>{};
    for (final item in (result['results'] as List?) ?? const []) {
      if (item is! Map) continue;
      final statement = item['statement'];
      if (statement is! String) continue;
      for (final rangeId in (item['verified_range_ids'] as List?) ?? const []) {
        if (rangeId is String) statementByRange[rangeId] = statement;
      }
    }
    final unknownIds = <String>{};
    for (final item in (result['results'] as List?) ?? const []) {
      if (item is! Map) continue;
      for (final rangeId in (item['verified_range_ids'] as List?) ?? const []) {
        if (rangeId is String && !knownIds.contains(rangeId))
          unknownIds.add(rangeId);
      }
    }
    final overview = result['overview'];
    final rawAnswer = result['raw_answer'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 6,
          children: [
            StatusPill(
              label: '${result['completion_status']}',
              icon: Icons.task_alt,
              color: const Color(0xff2c6a4b),
            ),
            StatusPill(
              label: '${result['answer_source']}',
              icon: Icons.source_outlined,
            ),
          ],
        ),
        if (overview is String && overview.isNotEmpty) ...[
          const SizedBox(height: 10),
          _NarrativePanel(
            title: 'Answer overview',
            icon: Icons.summarize_outlined,
            text: overview,
          ),
        ],
        if (rawAnswer is String && rawAnswer.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: _NarrativePanel(
              title: 'Synthesized answer',
              icon: Icons.article_outlined,
              text: rawAnswer,
              emphasized: true,
            ),
          ),
        _ResultsSection(
          title: 'High-probability results',
          highProbability: true,
          entries: classifiedConversationResults(
            result,
            probability: 'high_probability',
          ),
        ),
        _ResultsSection(
          title: 'Lower-probability results',
          highProbability: false,
          entries: classifiedConversationResults(
            result,
            probability: 'lower_probability',
          ),
        ),
        if (result['unclassified_evidence'] is List &&
            (result['unclassified_evidence'] as List).isNotEmpty)
          _JsonSection(
            title: 'Unclassified validated evidence',
            value: result['unclassified_evidence'],
          ),
        if (result['unverified_model_statements'] is List &&
            (result['unverified_model_statements'] as List).isNotEmpty)
          _JsonSection(
            title: 'Unverified model statements',
            value: result['unverified_model_statements'],
          ),
        if (unknownIds.isNotEmpty)
          _JsonSection(
            title: 'Warnings: unknown range IDs (not navigable)',
            value: unknownIds.toList(),
          ),
        _JsonSection(title: 'Coverage', value: result['coverage']),
        _JsonSection(
          title: 'Warnings and processing details',
          value: {
            'uncertainties': result['uncertainties'],
            'retrieval_diagnostics': result['retrieval_diagnostics'],
            'ledger_processing': result['ledger_processing'],
            'evidence_validation': result['evidence_validation'],
            'synthesis_validation': result['synthesis_validation'],
            'strategy': result['strategy'],
          },
        ),
        if (ledger.isNotEmpty) ...[
          const SizedBox(height: 8),
          const SectionHeader(
            title: 'Canonical evidence ranges',
            description:
                'Validated ranges available for transcript review and evidence-block creation.',
            leading: Icon(Icons.fact_check_outlined, size: 19),
          ),
          const SizedBox(height: 5),
          ...ledger.map(
            (range) => _RangeTile(
              range: range,
              statement: statementByRange[range['range_id']],
              database: database,
              revision: revision,
              onView: () => onViewRange(range),
              onSave: () => onSaveRange(
                range,
                statement: statementByRange[range['range_id']],
              ),
            ),
          ),
        ],
        ExpansionTile(
          title: const Text('Complete canonical result'),
          children: [
            Padding(
              padding: const EdgeInsets.all(8),
              child: SelectableText(
                const JsonEncoder.withIndent('  ').convert(result),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

List<Map<String, dynamic>> classifiedConversationResults(
  Map<String, dynamic> result, {
  required String probability,
}) {
  if (probability != 'high_probability' && probability != 'lower_probability') {
    throw ArgumentError.value(probability, 'probability');
  }
  return ((result['results'] as List?) ?? const [])
      .whereType<Map>()
      .map((item) => item.cast<String, dynamic>())
      .where(
        (item) =>
            item['classification_status'] == 'model_classified' &&
            item['probability'] == probability,
      )
      .toList();
}

class _NarrativePanel extends StatelessWidget {
  const _NarrativePanel({
    required this.title,
    required this.icon,
    required this.text,
    this.emphasized = false,
  });

  final String title;
  final IconData icon;
  final String text;
  final bool emphasized;

  @override
  Widget build(BuildContext context) => SectionSurface(
    backgroundColor: emphasized
        ? Theme.of(context).colorScheme.primaryContainer.withValues(alpha: 0.38)
        : Theme.of(context).colorScheme.surfaceContainerLow,
    borderColor: emphasized
        ? Theme.of(context).colorScheme.primary.withValues(alpha: 0.5)
        : null,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionHeader(title: title, leading: Icon(icon, size: 19)),
        const SizedBox(height: 8),
        SelectableText(
          text,
          style: Theme.of(context).textTheme.bodyLarge?.copyWith(height: 1.55),
        ),
      ],
    ),
  );
}

class _ResultsSection extends StatelessWidget {
  const _ResultsSection({
    required this.title,
    required this.entries,
    required this.highProbability,
  });

  final String title;
  final List<Map<String, dynamic>> entries;
  final bool highProbability;

  @override
  Widget build(BuildContext context) => entries.isEmpty
      ? const SizedBox.shrink()
      : Padding(
          padding: const EdgeInsets.only(top: 8),
          child: SectionSurface(
            backgroundColor: highProbability
                ? const Color(0xffedf6f0)
                : const Color(0xfffff7df),
            borderColor: highProbability
                ? const Color(0xff8db39b)
                : const Color(0xffceb36b),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SectionHeader(
                  title: title,
                  description: highProbability
                      ? 'Evidence the model classified with higher confidence.'
                      : 'Potentially relevant evidence requiring closer review.',
                  leading: Icon(
                    highProbability
                        ? Icons.verified_outlined
                        : Icons.low_priority,
                    size: 19,
                    color: highProbability
                        ? const Color(0xff2c6a4b)
                        : const Color(0xff7a5d0a),
                  ),
                ),
                const SizedBox(height: 6),
                ...entries.map(
                  (entry) => Container(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    decoration: const BoxDecoration(
                      border: Border(top: BorderSide(color: Color(0x337b8992))),
                    ),
                    child: SelectableText(
                      '${entry['statement']}\nCitation: ${entry['citation_status']}  Probability: ${entry['probability']}\nWarnings: ${entry['warnings']}',
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
}

class _JsonSection extends StatelessWidget {
  const _JsonSection({required this.title, required this.value});

  final String title;
  final Object? value;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(top: 5),
    decoration: BoxDecoration(
      color: title.startsWith('Warnings')
          ? const Color(0xfffff7df)
          : Theme.of(context).colorScheme.surfaceContainerLow,
      border: Border.all(
        color: title.startsWith('Warnings')
            ? const Color(0xffceb36b)
            : Theme.of(context).colorScheme.outlineVariant,
      ),
      borderRadius: BorderRadius.circular(4),
    ),
    child: ExpansionTile(
      leading: Icon(
        title.startsWith('Warnings')
            ? Icons.warning_amber_outlined
            : Icons.data_object,
        size: 18,
      ),
      title: Text(title, style: Theme.of(context).textTheme.titleSmall),
      children: [
        const Divider(height: 1),
        Padding(
          padding: const EdgeInsets.all(10),
          child: Align(
            alignment: Alignment.centerLeft,
            child: SelectableText(
              const JsonEncoder.withIndent('  ').convert(value),
            ),
          ),
        ),
      ],
    ),
  );
}

class _RangeTile extends StatelessWidget {
  const _RangeTile({
    required this.range,
    required this.statement,
    required this.database,
    required this.revision,
    required this.onView,
    required this.onSave,
  });

  final Map<String, dynamic> range;
  final String? statement;
  final EvwDatabase database;
  final RevisionSummary revision;
  final VoidCallback onView;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    final start = range['start_message_id'];
    final end = range['end_message_id'];
    final description = statement?.trim().isNotEmpty == true
        ? statement!
        : '${range['summary'] ?? range['relevance'] ?? ''}';
    final valid =
        start is String &&
        end is String &&
        database.coreMessageForRange(revision.id, start, end) != null;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Card(
        child: ListTile(
          leading: Icon(
            valid ? Icons.link : Icons.link_off,
            color: valid
                ? Theme.of(context).colorScheme.primary
                : Theme.of(context).colorScheme.error,
          ),
          title: Text('${range['range_id']}  $description'),
          subtitle: Text(
            '${range['start_message_id']} -> ${range['end_message_id']}\n${range['uncertainties']}',
          ),
          isThreeLine: true,
          trailing: Wrap(
            spacing: 4,
            children: [
              IconButton(
                tooltip: 'View in transcript',
                onPressed: valid ? onView : null,
                icon: const Icon(Icons.center_focus_strong),
              ),
              IconButton(
                tooltip: 'Save evidence block',
                onPressed: valid ? onSave : null,
                icon: const Icon(Icons.bookmark_add_outlined),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _formatDuration(Duration value) {
  final seconds = value.inSeconds;
  final hours = seconds ~/ 3600;
  final minutes = (seconds % 3600) ~/ 60;
  final remainder = seconds % 60;
  if (hours > 0) {
    return '$hours:${minutes.toString().padLeft(2, '0')}:${remainder.toString().padLeft(2, '0')}';
  }
  return '${minutes.toString().padLeft(2, '0')}:${remainder.toString().padLeft(2, '0')}';
}
