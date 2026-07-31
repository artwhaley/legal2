import 'dart:ui' show AppExitResponse;

import 'package:flutter/material.dart';

import 'conversation_page.dart';
import 'corpus_page.dart';
import 'print_output_page.dart';
import 'search_page.dart';
import 'server_gateway.dart';
import 'transcript_page.dart';
import 'workspace_controller.dart';

class WorkspaceView extends StatefulWidget {
  const WorkspaceView({super.key, this.initialPath, required this.gateway});

  final String? initialPath;
  final ServerGateway gateway;

  @override
  State<WorkspaceView> createState() => _WorkspaceViewState();
}

class _WorkspaceViewState extends State<WorkspaceView>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late final WorkspaceController workspace;
  late final TabController _tabs;
  String? _exitRefusal;

  @override
  void initState() {
    super.initState();
    workspace = WorkspaceController(gateway: widget.gateway);
    _tabs = TabController(length: 5, vsync: this);
    _tabs.addListener(_onTabChanged);
    workspace.addListener(_onWorkspaceChanged);
    WidgetsBinding.instance.addObserver(this);
    if (widget.initialPath != null) {
      workspace.open(widget.initialPath!).catchError((_) {});
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    workspace.removeListener(_onWorkspaceChanged);
    _tabs.removeListener(_onTabChanged);
    _tabs.dispose();
    workspace.dispose();
    if (widget.gateway case final HttpServerGateway gateway) {
      gateway.close();
    }
    super.dispose();
  }

  void _onTabChanged() {
    if (mounted) setState(() {});
  }

  void _onWorkspaceChanged() {
    if (!workspace.remoteOperationActive && _exitRefusal != null && mounted) {
      setState(() => _exitRefusal = null);
    }
  }

  @override
  Future<AppExitResponse> didRequestAppExit() async {
    if (!workspace.remoteOperationActive) return AppExitResponse.exit;
    if (mounted) {
      setState(() {
        _exitRefusal =
            'Cannot close the application while '
            '"${workspace.remoteOperationLabel}" is active. '
            'Cancel it or wait for it to finish.';
      });
    }
    return AppExitResponse.cancel;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      toolbarHeight: 68,
      titleSpacing: 20,
      title: Row(
        children: [
          Container(
            width: 34,
            height: 34,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primary,
              borderRadius: BorderRadius.circular(4),
            ),
            child: const Icon(
              Icons.fact_check_outlined,
              size: 20,
              color: Colors.white,
            ),
          ),
          const SizedBox(width: 11),
          Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'EVW v15 viewer',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              Text(
                'Evidence analysis workstation',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
          const Spacer(),
          ListenableBuilder(
            listenable: workspace,
            builder: (context, _) {
              final corpus = workspace.selectedCorpus;
              final revision = workspace.selectedRevision;
              return ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      corpus == null ? 'No corpus selected' : corpus.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    Text(
                      revision == null
                          ? workspace.isOpen
                                ? 'EVW open · select a ready corpus'
                                : 'No EVW open'
                          : 'Revision ${revision.number} · ${revision.messages} messages',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ),
      bottom: TabBar(
        controller: _tabs,
        isScrollable: true,
        tabAlignment: TabAlignment.start,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        labelPadding: const EdgeInsets.symmetric(horizontal: 18),
        tabs: const [
          Tab(
            height: 48,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.storage_outlined, size: 18),
                SizedBox(width: 7),
                Text('Corpus'),
              ],
            ),
          ),
          Tab(
            height: 48,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.search, size: 18),
                SizedBox(width: 7),
                Text('Search'),
              ],
            ),
          ),
          Tab(
            height: 48,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.question_answer_outlined, size: 18),
                SizedBox(width: 7),
                Text('Conversation'),
              ],
            ),
          ),
          Tab(
            height: 48,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.subject_outlined, size: 18),
                SizedBox(width: 7),
                Text('Transcript'),
              ],
            ),
          ),
          Tab(
            height: 48,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.description_outlined, size: 18),
                SizedBox(width: 7),
                Text('Print output'),
              ],
            ),
          ),
        ],
      ),
    ),
    body: Column(
      children: [
        if (_exitRefusal != null && workspace.remoteOperationActive)
          MaterialBanner(
            content: SelectableText(_exitRefusal!),
            actions: const [SizedBox.shrink()],
          ),
        Expanded(
          child: ListenableBuilder(
            listenable: workspace,
            builder: (context, _) => IndexedStack(
              index: _tabs.index,
              children: [
                CorpusPage(workspace: workspace),
                SearchPage(
                  workspace: workspace,
                  isPageActive: _tabs.index == 1,
                ),
                ConversationPage(
                  workspace: workspace,
                  isPageActive: _tabs.index == 2,
                ),
                TranscriptPage(
                  workspace: workspace,
                  isPageActive: _tabs.index == 3,
                ),
                PrintOutputPage(workspace: workspace),
              ],
            ),
          ),
        ),
      ],
    ),
  );
}
