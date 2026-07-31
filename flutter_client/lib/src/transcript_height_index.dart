class _FenwickTree {
  _FenwickTree(this.size) : values = List<double>.filled(size + 1, 0);

  final int size;
  final List<double> values;

  void add(int index, double delta) {
    if (index < 0 || index >= size) return;
    var position = index + 1;
    while (position <= size) {
      values[position] += delta;
      position += position & -position;
    }
  }

  double prefixSum(int endExclusive) {
    var position = endExclusive.clamp(0, size);
    var total = 0.0;
    while (position > 0) {
      total += values[position];
      position -= position & -position;
    }
    return total;
  }

  int ordinalForOffset(double target) {
    if (size == 0) return 0;
    var index = 0;
    var accumulated = 0.0;
    var bit = 1;
    while ((bit << 1) <= size) {
      bit <<= 1;
    }
    while (bit != 0) {
      final next = index + bit;
      if (next <= size && accumulated + values[next] <= target) {
        accumulated += values[next];
        index = next;
      }
      bit >>= 1;
    }
    return index.clamp(0, size - 1);
  }
}

class TranscriptHeightIndex {
  TranscriptHeightIndex(this.messageCount, {this.defaultHeight = 92})
    : _heights = List<double>.filled(messageCount, defaultHeight),
      _measured = List<bool>.filled(messageCount, false),
      _tree = _FenwickTree(messageCount) {
    for (var ordinal = 0; ordinal < messageCount; ordinal++) {
      _tree.add(ordinal, defaultHeight);
    }
  }

  final int messageCount;
  double defaultHeight;
  List<double> _heights;
  List<bool> _measured;
  _FenwickTree _tree;

  double get totalHeight => _tree.prefixSum(messageCount);
  int get measuredCount => _measured.where((value) => value).length;

  double heightAt(int ordinal) =>
      ordinal < 0 || ordinal >= messageCount ? 0 : _heights[ordinal];

  double offsetForOrdinal(int ordinal) =>
      _tree.prefixSum(ordinal.clamp(0, messageCount));

  int ordinalForOffset(double offset) {
    if (messageCount == 0) return 0;
    final clamped = offset
        .clamp(0, (totalHeight - 0.01).clamp(0, double.infinity))
        .toDouble();
    return _tree.ordinalForOffset(clamped);
  }

  bool setHeight(int ordinal, double height) {
    if (ordinal < 0 || ordinal >= messageCount) return false;
    final next = height.clamp(28, 10000).toDouble();
    final delta = next - _heights[ordinal];
    if (delta.abs() < 0.5) {
      _measured[ordinal] = true;
      return false;
    }
    _heights[ordinal] = next;
    _measured[ordinal] = true;
    _tree.add(ordinal, delta);
    return true;
  }

  void invalidate({double? estimatedHeight}) {
    if (estimatedHeight != null) defaultHeight = estimatedHeight;
    _heights = List<double>.filled(messageCount, defaultHeight);
    _measured = List<bool>.filled(messageCount, false);
    _tree = _FenwickTree(messageCount);
    for (var ordinal = 0; ordinal < messageCount; ordinal++) {
      _tree.add(ordinal, defaultHeight);
    }
  }
}
