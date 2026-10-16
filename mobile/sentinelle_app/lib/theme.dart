import 'package:flutter/material.dart';

/// Couleurs sémantiques : vert = actif, ambre = pause, rouge = arrêt.
const seed = Color(0xFF1B5E4A);
const okColor = Color(0xFF2E7D32);
const warnColor = Color(0xFFB26A00);
const dangerColor = Color(0xFFC62828);

ThemeData buildTheme(Brightness brightness) {
  final scheme = ColorScheme.fromSeed(seedColor: seed, brightness: brightness);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    cardTheme: const CardThemeData(margin: EdgeInsets.symmetric(horizontal: 16, vertical: 6)),
    inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
  );
}

Color statusColor(String status) => switch (status) {
      'ACTIVE' => okColor,
      'PAUSED_DAILY' || 'PAUSED_LOSS_STREAK' || 'WAITING_FOR_BOT' => warnColor,
      _ => dangerColor,
    };
