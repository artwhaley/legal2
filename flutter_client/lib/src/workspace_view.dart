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
      title: const Text('EVW v15 viewer'),
      bottom: TabBar(
        controller: _tabs,
        tabs: const [
          Tab(text: 'Corpus'),
          Tab(text: 'Search'),
          Tab(text: 'Conversation'),
          Tab(text: 'Transcript'),
          Tab(text: 'Print output'),
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
