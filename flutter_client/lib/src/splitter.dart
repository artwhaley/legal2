import 'package:flutter/material.dart';

class ResizableSplitter extends StatefulWidget {
  const ResizableSplitter({
    super.key,
    required this.primary,
    required this.secondary,
    required this.initialPrimarySize,
    required this.primaryMin,
    required this.secondaryMin,
    required this.onDragEnd,
    this.dividerExtent = 8,
  });

  final Widget primary;
  final Widget secondary;
  final double initialPrimarySize;
  final double primaryMin;
  final double secondaryMin;
  final ValueChanged<double> onDragEnd;
  final double dividerExtent;

  @override
  State<ResizableSplitter> createState() => _ResizableSplitterState();
}

class _ResizableSplitterState extends State<ResizableSplitter> {
  late double _size = widget.initialPrimarySize;
  bool _dragging = false;

  @override
  void didUpdateWidget(ResizableSplitter oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_dragging &&
        oldWidget.initialPrimarySize != widget.initialPrimarySize) {
      _size = widget.initialPrimarySize;
    }
  }

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final available = constraints.maxWidth - widget.dividerExtent;
      if (available < widget.primaryMin + widget.secondaryMin) {
        return Column(
          children: [
            Expanded(child: widget.primary),
            const SizedBox(height: 8),
            Expanded(child: widget.secondary),
          ],
        );
      }
      final maxPrimary = available - widget.secondaryMin;
      final primarySize = _size.clamp(widget.primaryMin, maxPrimary).toDouble();
      return Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(width: primarySize, child: widget.primary),
          MouseRegion(
            cursor: SystemMouseCursors.resizeColumn,
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onHorizontalDragStart: (_) => setState(() => _dragging = true),
              onHorizontalDragUpdate: (details) {
                setState(() {
                  _size = (_size + details.delta.dx)
                      .clamp(widget.primaryMin, maxPrimary)
                      .toDouble();
                });
              },
              onHorizontalDragEnd: (_) {
                setState(() => _dragging = false);
                widget.onDragEnd(primarySize);
              },
              child: SizedBox(
                width: widget.dividerExtent,
                child: Center(
                  child: Container(
                    width: 1,
                    color: Theme.of(context).colorScheme.outlineVariant,
                  ),
                ),
              ),
            ),
          ),
          Expanded(child: widget.secondary),
        ],
      );
    },
  );
}
