import 'package:flutter/material.dart';

abstract final class AppTheme {
  static const ink = Color(0xff17232d);
  static const mutedInk = Color(0xff53636f);
  static const navy = Color(0xff28516b);
  static const line = Color(0xffcbd3d8);
  static const canvas = Color(0xfff3f5f6);
  static const paper = Color(0xfffbfcfc);

  static ThemeData get light {
    const scheme = ColorScheme.light(
      primary: navy,
      onPrimary: Colors.white,
      primaryContainer: Color(0xffdbe8ef),
      onPrimaryContainer: Color(0xff112f40),
      secondary: Color(0xff4f626f),
      onSecondary: Colors.white,
      secondaryContainer: Color(0xffe1e8ec),
      onSecondaryContainer: Color(0xff263842),
      tertiary: Color(0xff626039),
      onTertiary: Colors.white,
      tertiaryContainer: Color(0xffece9c8),
      onTertiaryContainer: Color(0xff343413),
      error: Color(0xffa93632),
      onError: Colors.white,
      errorContainer: Color(0xffffe4e1),
      onErrorContainer: Color(0xff5c1715),
      surface: paper,
      onSurface: ink,
      onSurfaceVariant: mutedInk,
      outline: Color(0xff7b8992),
      outlineVariant: line,
      surfaceContainerLowest: Colors.white,
      surfaceContainerLow: Color(0xfff7f9f9),
      surfaceContainer: Color(0xffeef1f2),
      surfaceContainerHigh: Color(0xffe7ebed),
      surfaceContainerHighest: Color(0xffdfe5e8),
    );
    final base = ThemeData(
      colorScheme: scheme,
      useMaterial3: true,
      fontFamily: 'Segoe UI',
      scaffoldBackgroundColor: canvas,
      visualDensity: VisualDensity.compact,
      focusColor: navy.withValues(alpha: 0.16),
      hoverColor: navy.withValues(alpha: 0.06),
    );
    final textTheme = base.textTheme.copyWith(
      headlineSmall: const TextStyle(
        fontSize: 22,
        height: 1.2,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.2,
        color: ink,
      ),
      titleLarge: const TextStyle(
        fontSize: 18,
        height: 1.25,
        fontWeight: FontWeight.w600,
        color: ink,
      ),
      titleMedium: const TextStyle(
        fontSize: 15,
        height: 1.3,
        fontWeight: FontWeight.w600,
        color: ink,
      ),
      titleSmall: const TextStyle(
        fontSize: 13,
        height: 1.3,
        fontWeight: FontWeight.w600,
        color: ink,
      ),
      bodyLarge: const TextStyle(fontSize: 15, height: 1.5, color: ink),
      bodyMedium: const TextStyle(fontSize: 14, height: 1.45, color: ink),
      bodySmall: const TextStyle(fontSize: 12.5, height: 1.4, color: mutedInk),
      labelLarge: const TextStyle(
        fontSize: 13,
        height: 1.2,
        fontWeight: FontWeight.w600,
      ),
      labelMedium: const TextStyle(
        fontSize: 12,
        height: 1.2,
        fontWeight: FontWeight.w600,
      ),
    );
    final focusedOverlay = WidgetStateProperty.resolveWith<Color?>((states) {
      if (states.contains(WidgetState.focused)) {
        return navy.withValues(alpha: 0.14);
      }
      if (states.contains(WidgetState.hovered)) {
        return navy.withValues(alpha: 0.06);
      }
      return null;
    });
    return base.copyWith(
      textTheme: textTheme,
      appBarTheme: const AppBarTheme(
        backgroundColor: paper,
        foregroundColor: ink,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
      ),
      tabBarTheme: TabBarThemeData(
        labelColor: navy,
        unselectedLabelColor: mutedInk,
        indicatorColor: navy,
        dividerColor: line,
        overlayColor: focusedOverlay,
        labelStyle: textTheme.labelLarge,
        unselectedLabelStyle: textTheme.labelLarge,
      ),
      cardTheme: const CardThemeData(
        color: paper,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(6)),
          side: BorderSide(color: line),
        ),
      ),
      dividerTheme: const DividerThemeData(color: line, thickness: 1),
      inputDecorationTheme: const InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        isDense: true,
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.all(Radius.circular(4)),
          borderSide: BorderSide(color: Color(0xff89969e)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.all(Radius.circular(4)),
          borderSide: BorderSide(color: Color(0xff89969e)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.all(Radius.circular(4)),
          borderSide: BorderSide(color: navy, width: 2),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll(Size(0, 38)),
          padding: const WidgetStatePropertyAll(
            EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          ),
          shape: const WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(4)),
            ),
          ),
          overlayColor: focusedOverlay,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll(Size(0, 38)),
          padding: const WidgetStatePropertyAll(
            EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          ),
          shape: const WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(4)),
            ),
          ),
          side: const WidgetStatePropertyAll(BorderSide(color: line)),
          overlayColor: focusedOverlay,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll(Size(0, 36)),
          shape: const WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(4)),
            ),
          ),
          overlayColor: focusedOverlay,
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: ButtonStyle(overlayColor: focusedOverlay),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll(Size(0, 38)),
          shape: const WidgetStatePropertyAll(
            RoundedRectangleBorder(
              borderRadius: BorderRadius.all(Radius.circular(4)),
            ),
          ),
          side: const WidgetStatePropertyAll(BorderSide(color: line)),
          overlayColor: focusedOverlay,
        ),
      ),
      chipTheme: base.chipTheme.copyWith(
        backgroundColor: scheme.surfaceContainer,
        side: const BorderSide(color: line),
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(4)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 4),
        labelStyle: textTheme.labelMedium,
      ),
      listTileTheme: const ListTileThemeData(
        iconColor: mutedInk,
        selectedColor: navy,
        selectedTileColor: Color(0xffe5edf2),
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 2),
        minVerticalPadding: 8,
      ),
      bannerTheme: const MaterialBannerThemeData(
        backgroundColor: Color(0xfffff1ef),
        surfaceTintColor: Colors.transparent,
        padding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: Color(0xff27343d),
        contentTextStyle: TextStyle(color: Colors.white),
      ),
      tooltipTheme: const TooltipThemeData(
        waitDuration: Duration(milliseconds: 450),
        decoration: BoxDecoration(
          color: Color(0xff27343d),
          borderRadius: BorderRadius.all(Radius.circular(3)),
        ),
        textStyle: TextStyle(color: Colors.white, fontSize: 12),
      ),
    );
  }
}
