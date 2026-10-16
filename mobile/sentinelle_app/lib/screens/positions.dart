import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../theme.dart';
import 'home.dart';

class PositionsScreen extends StatelessWidget {
  const PositionsScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return AsyncPage<Map<String, dynamic>>(
      load: api.trades,
      refreshEvery: const Duration(seconds: 60),
      builder: (context, data, reload) {
        final open = (data['open'] as List).cast<Map<String, dynamic>>();
        final closed = (data['closed'] as List).cast<Map<String, dynamic>>();
        final text = Theme.of(context).textTheme;
        return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          if (data['error'] != null)
            Card(child: ListTile(leading: const Icon(Icons.warning_amber), title: Text('${data['error']}'))),
          Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text('Positions ouvertes', style: text.titleMedium)),
          if (open.isEmpty) const ListTile(title: Text('Aucune position : le capital est en USDT.')),
          ...open.map((t) => Card(
                child: ListTile(
                  title: Text('${t['pair']}'),
                  subtitle: Text('Entrée ${t['open_rate']} · mise ${usdt(t['stake_amount'] as num?)}'
                      '\nStop ${t['stop_loss_abs'] ?? '—'} · ouvert le ${shortDate(t['open_date'] as String?)}'),
                  isThreeLine: true,
                  trailing: _Pnl(t['profit_ratio'] as num?),
                ),
              )),
          Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text('Journal des trades', style: text.titleMedium)),
          if (closed.isEmpty) const ListTile(title: Text('Aucun trade terminé pour l\'instant.')),
          ...closed.reversed.where((t) => t['is_open'] != true).map((t) => ListTile(
                dense: true,
                title: Text('${t['pair']} · ${shortDate(t['close_date'] as String?)}'),
                subtitle: Text('Sortie : ${t['exit_reason'] ?? '—'}'),
                trailing: _Pnl(t['profit_ratio'] as num?),
              )),
        ]);
      },
    );
  }
}

class _Pnl extends StatelessWidget {
  const _Pnl(this.ratio);
  final num? ratio;
  @override
  Widget build(BuildContext context) {
    final r = ratio ?? 0;
    return Text(pct(r, signed: true),
        style: TextStyle(fontWeight: FontWeight.w600, color: r >= 0 ? okColor : dangerColor));
  }
}
