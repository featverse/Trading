// Formats d'affichage : montants en FCFA, pourcentages, dates.

String fcfa(num? value) {
  if (value == null) return '—';
  final rounded = value.round();
  final negative = rounded < 0;
  final digits = rounded.abs().toString();
  final buf = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buf.write(' '); // espace fine insécable
    buf.write(digits[i]);
  }
  return '${negative ? '−' : ''}${buf.toString()} FCFA';
}

String pct(num? value, {int decimals = 1, bool signed = false}) {
  if (value == null) return '—';
  final p = value * 100;
  final text = p.abs().toStringAsFixed(decimals).replaceAll('.', ',');
  final sign = p < 0 ? '−' : (signed && p > 0 ? '+' : '');
  return '$sign$text %';
}

String usdt(num? value) => value == null ? '—' : '${value.toStringAsFixed(2).replaceAll('.', ',')} USDT';

String shortDate(String? iso) {
  if (iso == null || iso.isEmpty) return '—';
  final d = DateTime.tryParse(iso)?.toLocal();
  if (d == null) return iso;
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(d.day)}/${two(d.month)}/${d.year} ${two(d.hour)}:${two(d.minute)}';
}

/// Libellés français des statuts du gardien.
String statusLabel(String status) => switch (status) {
      'ACTIVE' => 'Actif',
      'PAUSED_DAILY' => 'Pause du jour',
      'PAUSED_LOSS_STREAK' => 'Pause (série de pertes)',
      'HALTED' => 'Arrêt de sécurité',
      'WAITING_FOR_BOT' => 'En attente du bot',
      _ => status,
    };

String decisionLabel(String? decision) => switch (decision) {
      'PAPER_TRADING_ONLY' => 'Validée — simulation',
      'REJECTED' => 'Rejetée',
      _ => decision ?? '—',
    };
