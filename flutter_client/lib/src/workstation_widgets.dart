import 'package:flutter/material.dart';

enum OperationalTone { info, success, warning, failure }

class WorkstationPage extends StatelessWidget {
  const WorkstationPage({
    super.key,
    required this.title,
    required this.description,
    required this.child,
    this.actions = const [],
    this.padding = const EdgeInsets.fromLTRB(20, 18, 20, 20),
  });

  final String title;
  final String description;
  final Widget child;
  final List<Widget> actions;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) => Padding(
    padding: padding,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        LayoutBuilder(
          builder: (context, constraints) {
            final heading = Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 3),
                Text(description, style: Theme.of(context).textTheme.bodySmall),
              ],
            );
            if (actions.isEmpty) return heading;
            final controls = Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: actions,
            );
            if (constraints.maxWidth < 760) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [heading, const SizedBox(height: 12), controls],
              );
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: heading),
                const SizedBox(width: 24),
                controls,
              ],
            );
          },
        ),
        const SizedBox(height: 16),
        Expanded(child: child),
      ],
    ),
  );
}

class SectionSurface extends StatelessWidget {
  const SectionSurface({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(14),
    this.backgroundColor,
    this.borderColor,
    this.clipBehavior = Clip.none,
  });

  final Widget child;
  final EdgeInsets padding;
  final Color? backgroundColor;
  final Color? borderColor;
  final Clip clipBehavior;

  @override
  Widget build(BuildContext context) => Container(
    clipBehavior: clipBehavior,
    padding: padding,
    decoration: BoxDecoration(
      color: backgroundColor ?? Theme.of(context).colorScheme.surface,
      border: Border.all(
        color: borderColor ?? Theme.of(context).colorScheme.outlineVariant,
      ),
      borderRadius: BorderRadius.circular(6),
    ),
    child: child,
  );
}

class SectionHeader extends StatelessWidget {
  const SectionHeader({
    super.key,
    required this.title,
    this.description,
    this.leading,
    this.trailing,
  });

  final String title;
  final String? description;
  final Widget? leading;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      if (leading != null) ...[leading!, const SizedBox(width: 9)],
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            if (description != null) ...[
              const SizedBox(height: 2),
              Text(description!, style: Theme.of(context).textTheme.bodySmall),
            ],
          ],
        ),
      ),
      if (trailing != null) ...[const SizedBox(width: 12), trailing!],
    ],
  );
}

class EmptyWorkspaceState extends StatelessWidget {
  const EmptyWorkspaceState({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) => Center(
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 480),
      child: SectionSurface(
        backgroundColor: Theme.of(context).colorScheme.surfaceContainerLow,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 28,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(height: 10),
              Text(
                title,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 5),
              Text(
                message,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class OperationalMessage extends StatelessWidget {
  const OperationalMessage({
    super.key,
    required this.message,
    this.tone = OperationalTone.info,
    this.label,
    this.trailing,
  });

  final String message;
  final OperationalTone tone;
  final String? label;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final (icon, foreground, background, border) = switch (tone) {
      OperationalTone.info => (
        Icons.info_outline,
        colors.onPrimaryContainer,
        colors.primaryContainer.withValues(alpha: 0.48),
        colors.primary.withValues(alpha: 0.38),
      ),
      OperationalTone.success => (
        Icons.check_circle_outline,
        const Color(0xff1d5138),
        const Color(0xffe3f2e9),
        const Color(0xff7aa98d),
      ),
      OperationalTone.warning => (
        Icons.warning_amber_outlined,
        const Color(0xff624b0a),
        const Color(0xfffff3d3),
        const Color(0xffc5a85c),
      ),
      OperationalTone.failure => (
        Icons.error_outline,
        colors.onErrorContainer,
        colors.errorContainer,
        colors.error.withValues(alpha: 0.55),
      ),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: background,
        border: Border.all(color: border),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: foreground),
          const SizedBox(width: 9),
          Expanded(
            child: SelectableText(
              label == null ? message : '$label\n$message',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: foreground),
            ),
          ),
          if (trailing != null) ...[const SizedBox(width: 12), trailing!],
        ],
      ),
    );
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, this.icon, this.color});

  final String label;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final resolved = color ?? Theme.of(context).colorScheme.secondary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: resolved.withValues(alpha: 0.09),
        border: Border.all(color: resolved.withValues(alpha: 0.42)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 13, color: resolved),
            const SizedBox(width: 5),
          ],
          Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: resolved,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
