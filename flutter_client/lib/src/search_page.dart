import 'package:flutter/material.dart';

import 'evw_models.dart';
import 'search_workflow.dart';
import 'server_contracts.dart';
import 'server_gateway.dart';
import 'transcript_editor.dart';
import 'workstation_widgets.dart';
import 'workspace_controller.dart';

class SearchPage extends StatefulWidget {
  const SearchPage({
    super.key,
    required this.workspace,
    required this.isPageActive,
  });

  final WorkspaceController workspace;
  final bool isPageActive;

  @override
  State<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends State<SearchPage> {
  final TextEditingController _query = TextEditingController();
  final TextEditingController _topK = TextEditingController(text: '20');
  final GlobalKey<TranscriptEvidenceEditorState> _editorKey = GlobalKey();
  List<SearchHit> _hits = [];
  int _total = 0;
  int? _nextOffset;
  String? _error;
  String? _notice;
  bool _working = false;
  String _mode = 'fts';
  RequestCancellation? _cancellation;
  int? _loadedRevisionId;
  int? _loadedGeneration;

  WorkspaceController get workspace => widget.workspace;

  @override
  void initState() {
    super.initState();
    workspace.addListener(_onWorkspaceChanged);
  }

  @override
  void dispose() {
    workspace.removeListener(_onWorkspaceChanged);
    _query.dispose();
    _topK.dispose();
    super.dispose();
  }

  void _onWorkspaceChanged() {
    final revision = workspace.selectedRevision;
    final generation = revision?.generation;
    if (revision?.id != _loadedRevisionId || generation != _loadedGeneration) {
      if (!mounted) {
        _clearResults();
        return;
      }
      setState(_clearResults);
    }
    if (mounted) setState(() {});
  }

  void _clearResults() {
    _hits = [];
    _total = 0;
    _nextOffset = null;
    _error = null;
    _notice = null;
    _loadedRevisionId = null;
    _loadedGeneration = null;
  }

  Future<void> _search({bool append = false}) async {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) {
      setState(() => _error = 'Select a ready working corpus on Corpus first.');
      return;
    }
    final generation = revision.generation;
    if (generation == null) {
      setState(
        () => _error = 'The selected revision has no current index generation.',
      );
      return;
    }
    if (_mode == 'embedding') {
      if (append) {
        setState(
          () => _error =
              'Embedding search returns exactly the requested top results; use a new query.',
        );
        return;
      }
      final topK = int.tryParse(_topK.text.trim());
      if (topK == null || topK < 1 || topK > 1000) {
        setState(
          () => _error = 'Top results must be an integer from 1 to 1000.',
        );
        return;
      }
      setState(() {
        _hits = [];
        _total = 0;
        _nextOffset = null;
        _error = null;
        _notice = null;
        _working = true;
        _cancellation = RequestCancellation();
      });
      try {
        final hits = await EmbeddingSearchWorkflow(
          workspace,
        ).execute(_query.text, topK: topK, cancellation: _cancellation);
        if (!mounted) return;
        setState(() {
          _hits = hits;
          _total = hits.length;
          _loadedRevisionId = revision.id;
          _loadedGeneration = generation;
          _working = false;
          _cancellation = null;
        });
      } catch (error) {
        if (!mounted) return;
        setState(() {
          _working = false;
          _cancellation = null;
          if (error is GatewayError && error.cancelled) {
            _notice = error.toString();
            _error = null;
          } else {
            _error = '$error';
          }
        });
      }
      return;
    }
    if (!append) {
      setState(() {
        _hits = [];
        _total = 0;
        _nextOffset = null;
        _error = null;
        _notice = null;
        _working = true;
      });
    } else {
      setState(() => _working = true);
    }
    try {
      final page = database.ftsSearch(
        revision.id,
        _query.text,
        indexGeneration: generation,
        limit: 100,
        offset: append ? (_nextOffset ?? 0) : 0,
      );
      if (!mounted) return;
      setState(() {
        _hits = append ? [..._hits, ...page.hits] : page.hits;
        _total = page.totalCount;
        _nextOffset = page.nextOffset;
        _loadedRevisionId = revision.id;
        _loadedGeneration = generation;
        _working = false;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _working = false;
        _error = '$error';
      });
    }
  }

  void _cancelEmbedding() {
    _cancellation?.cancel();
    if (mounted) {
      setState(() {
        _notice = 'Cancellation requested. Waiting for the request to close.';
        _error = null;
      });
    }
  }

  void _view(SearchHit hit) {
    _editorKey.currentState?.focusMessage(hit.messageId);
  }

  void _save(SearchHit hit) {
    try {
      final block = _editorKey.currentState?.createEvidenceBlockForMessage(
        hit.messageId,
        createdBy: evidenceCreatorForSearchMode(_mode),
      );
      if (block == null)
        throw StateError('Search result is not in the selected revision');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Saved evidence block ${block.id}')),
        );
      }
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  @override
  Widget build(BuildContext context) {
    final database = workspace.database;
    final revision = workspace.selectedRevision;
    if (database == null || revision == null) {
      return const WorkstationPage(
        title: 'Evidence search',
        description:
            'Run exact full-text or semantic retrieval, then review each result in the shared transcript.',
        child: EmptyWorkspaceState(
          icon: Icons.manage_search,
          title: 'Search requires a working corpus',
          message: 'Select a ready working corpus on Corpus to search.',
        ),
      );
    }
    return WorkstationPage(
      title: 'Evidence search',
      description:
          'Run exact full-text or semantic retrieval, then review each result in the shared transcript.',
      child: LayoutBuilder(
        builder: (context, constraints) => Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SectionSurface(
              padding: const EdgeInsets.all(12),
              backgroundColor: Theme.of(
                context,
              ).colorScheme.surfaceContainerLow,
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  SizedBox(
                    width: 360,
                    child: TextField(
                      controller: _query,
                      decoration: const InputDecoration(
                        labelText: 'Search query',
                        hintText: 'Enter terms or a semantic query',
                        prefixIcon: Icon(Icons.search, size: 19),
                      ),
                      onSubmitted: (_) => _search(),
                    ),
                  ),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'fts', label: Text('FTS5')),
                      ButtonSegment(
                        value: 'embedding',
                        label: Text('Embedding'),
                      ),
                    ],
                    selected: {_mode},
                    onSelectionChanged: _working
                        ? null
                        : (selection) =>
                              setState(() => _mode = selection.single),
                  ),
                  if (_mode == 'embedding')
                    SizedBox(
                      width: 130,
                      child: TextField(
                        controller: _topK,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Top results',
                        ),
                      ),
                    ),
                  FilledButton(
                    onPressed: _working ? null : () => _search(),
                    child: Text(_working ? 'Searching…' : 'Search'),
                  ),
                  if (_cancellation != null)
                    OutlinedButton(
                      onPressed: _cancelEmbedding,
                      child: const Text('Cancel'),
                    ),
                ],
              ),
            ),
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
            const SizedBox(height: 10),
            SizedBox(
              height: (constraints.maxHeight * 0.31)
                  .clamp(185.0, 300.0)
                  .toDouble(),
              child: SectionSurface(
                padding: EdgeInsets.zero,
                clipBehavior: Clip.antiAlias,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(14, 11, 12, 10),
                      child: SectionHeader(
                        title: 'Search results',
                        description: '$_total matches · ${_hits.length} loaded',
                        leading: const Icon(
                          Icons.format_list_bulleted,
                          size: 19,
                        ),
                        trailing: _nextOffset == null
                            ? null
                            : OutlinedButton(
                                onPressed: _working
                                    ? null
                                    : () => _search(append: true),
                                child: const Text('Load more'),
                              ),
                      ),
                    ),
                    const Divider(height: 1),
                    Expanded(
                      child: _hits.isEmpty
                          ? const Center(
                              child: Text('No search results loaded.'),
                            )
                          : ListView.separated(
                              itemCount: _hits.length,
                              separatorBuilder: (_, _) =>
                                  const Divider(height: 1),
                              itemBuilder: (context, index) => _ResultTile(
                                hit: _hits[index],
                                onView: () => _view(_hits[index]),
                                onSave: () => _save(_hits[index]),
                              ),
                            ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 10),
            Expanded(
              child: TranscriptEvidenceEditor(
                key: _editorKey,
                database: database,
                revision: revision,
                controller: workspace.transcriptController,
                isPageActive: widget.isPageActive,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ResultTile extends StatelessWidget {
  const _ResultTile({
    required this.hit,
    required this.onView,
    required this.onSave,
  });

  final SearchHit hit;
  final VoidCallback onView;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    final score = hit.matchType == 'embedding'
        ? 'Rank ${hit.rank.toInt()} · Distance ${hit.distance!.toStringAsFixed(6)}'
        : 'FTS5 score ${hit.rank.toStringAsFixed(6)}';
    return ListTile(
      leading: Container(
        width: 32,
        height: 32,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainer,
          borderRadius: BorderRadius.circular(4),
        ),
        child: Icon(
          hit.matchType == 'embedding'
              ? Icons.hub_outlined
              : Icons.text_snippet_outlined,
          size: 17,
          color: Theme.of(context).colorScheme.primary,
        ),
      ),
      title: Text('${hit.sender} · ${hit.timestamp}'),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 2),
          Text(
            score,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.primary,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            hit.body,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ],
      ),
      trailing: Wrap(
        spacing: 4,
        children: [
          IconButton(
            tooltip: 'View in transcript',
            onPressed: onView,
            icon: const Icon(Icons.center_focus_strong),
          ),
          IconButton(
            tooltip: 'Save evidence block',
            onPressed: onSave,
            icon: const Icon(Icons.bookmark_add_outlined),
          ),
        ],
      ),
      onTap: onView,
    );
  }
}

String evidenceCreatorForSearchMode(String mode) => switch (mode) {
  'fts' => 'fts_search',
  'embedding' => 'embedding_search',
  _ => throw ArgumentError.value(mode, 'mode'),
};
