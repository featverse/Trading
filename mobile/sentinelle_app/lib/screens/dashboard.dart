import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../theme.dart';
import 'home.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return AsyncPage<Map<String, dynamic>>(
      load: api.status,
      refreshEvery: const Duration(seconds: 30),
      builder: (context, s, reload) {
        final status = s['status'] as String;
        final color = statusColor(status);
        final tier = s['tier'] as Map<String, dynamic>;
        final plan = s['plan'] as Map<String, dynamic>;
        final text = Theme.of(context).textTheme;
        final drawdown = (s['drawdown'] as num?)?.toDouble() ?? 0;
        final dayChange = (s['day_change'] as num?)?.toDouble() ?? 0;
        return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          // Statut
          Card(
            color: color.withValues(alpha: 0.12),
            child: ListTile(
              leading: Icon(status == 'ACTIVE' ? Icons.verified_user : Icons.pause_circle, color: color, size: 36),
              title: Text(statusLabel(status), style: text.titleLarge?.copyWith(color: color)),
              subtitle: Text(s['halt_reason'] as String? ??
                  (s['feed']?['ok'] == true ? 'Bot connecté' : 'Bot non joignable : aucune nouvelle entrée')),
            ),
          ),
          // Capital
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Capital du compte', style: text.labelLarge),
                const SizedBox(height: 4),
                Text(fcfa(s['equity_fcfa'] as num?), style: text.headlineMedium),
                Text(usdt(s['equity_usdt'] as num?), style: text.bodySmall),
                const SizedBox(height: 12),
                Row(children: [
                  _Metric(label: 'Aujourd\'hui', value: pct(dayChange, signed: true)),
                  _Metric(label: 'Depuis le plus haut', value: pct(drawdown)),
                  _Metric(label: 'Mis à l\'abri', value: fcfa(s['total_secured_fcfa'] as num?)),
                ]),
              ]),
            ),
          ),
          // Jauge de drawdown : 0 → -10 % (kill switch)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Marge avant arrêt de sécurité (−10 %)', style: text.labelLarge),
                const SizedBox(height: 8),
                LinearProgressIndicator(
                  value: (drawdown.abs() / 0.10).clamp(0, 1).toDouble(),
                  minHeight: 10,
                  color: drawdown <= -0.07 ? dangerColor : (drawdown <= -0.04 ? warnColor : okColor),
                  borderRadius: BorderRadius.circular(5),
                ),
                const SizedBox(height: 6),
                Text('Risque actuel par trade : ${pct(s['current_risk_pct'] as num?)}'
                    ' · Pertes d\'affilée : ${s['consecutive_losses']}'),
              ]),
            ),
          ),
          // Palier
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Palier ${tier['name']} → objectif ${fcfa(s['next_milestone_fcfa'] as num?)}', style: text.labelLarge),
                const SizedBox(height: 8),
                LinearProgressIndicator(
                  value: ((s['milestone_progress'] as num?) ?? 0).toDouble(),
                  minHeight: 10,
                  borderRadius: BorderRadius.circular(5),
                ),
                const SizedBox(height: 8),
                Text(tier['description'] as String),
                if (tier['live_trading'] != true)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text('Pas de trading réel à ce palier : l\'IA s\'entraîne en simulation.'),
                  ),
              ]),
            ),
          ),
          // Plan
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Ton plan : ${fcfa(plan['monthly_deposit_fcfa'] as num?)} par mois', style: text.labelLarge),
                const SizedBox(height: 8),
                _PlanRow('100 000 FCFA', plan['months_to_100k'] as Map<String, dynamic>),
                _PlanRow('1 000 000 FCFA', plan['months_to_1m'] as Map<String, dynamic>),
                const SizedBox(height: 6),
                Text('Projection à rendement constant, illustrative.', style: text.bodySmall),
              ]),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(s['disclaimer'] as String? ?? '', style: text.bodySmall, textAlign: TextAlign.center),
          ),
        ]);
      },
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          Text(value, style: Theme.of(context).textTheme.titleSmall),
        ]),
      );
}

class _PlanRow extends StatelessWidget {
  const _PlanRow(this.target, this.months);
  final String target;
  final Map<String, dynamic> months;

  String _m(dynamic v) => v == null ? '—' : '$v mois';

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Text('$target : ${_m(months['0%'])} (épargne seule) · ${_m(months['2%'])} (à 2 %/mois)'),
      );
}
