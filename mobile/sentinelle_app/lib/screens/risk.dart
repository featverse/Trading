import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../security.dart';
import '../theme.dart';
import 'home.dart';

class RiskScreen extends StatelessWidget {
  const RiskScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return AsyncPage<Map<String, dynamic>>(
      load: api.risk,
      builder: (context, r, reload) {
        final limits = (r['limits'] as Map).cast<String, dynamic>();
        final events = (r['guard_events'] as List).cast<Map<String, dynamic>>();
        final status = r['status'] as String;
        final text = Theme.of(context).textTheme;
        return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          Card(
            color: statusColor(status).withValues(alpha: 0.12),
            child: ListTile(
              leading: Icon(Icons.shield, color: statusColor(status), size: 32),
              title: Text('Gardien : ${statusLabel(status)}', style: text.titleMedium),
              subtitle: const Text('Il a le dernier mot sur chaque achat du bot.'),
            ),
          ),
          // ARRÊT D'URGENCE
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              height: 64,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: dangerColor, foregroundColor: Colors.white),
                icon: const Icon(Icons.stop_circle_outlined, size: 32),
                label: const Text('ARRÊT D\'URGENCE', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                onPressed: () => _emergency(context, reload),
              ),
            ),
          ),
          if (status == 'HALTED')
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: OutlinedButton.icon(
                icon: const Icon(Icons.restart_alt),
                label: const Text('Redémarrer (après analyse de la cause)'),
                onPressed: () => _reset(context, r['reset_confirmation'] as String, reload),
              ),
            ),
          Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text('Règles fixes', style: text.titleMedium)),
          _Rule('Marché', 'Spot uniquement, aucun levier'),
          _Rule('Risque par trade', pct(limits['risk_per_trade'] as num?)),
          _Rule('Taille maximale par position', pct(limits['max_position_pct'] as num?, decimals: 0)),
          _Rule('Exposition totale maximale', pct(limits['max_total_exposure'] as num?, decimals: 0)),
          _Rule('Perte maximale par jour', pct(limits['daily_loss_limit'] as num?, decimals: 0)),
          _Rule('Arrêt complet à', '−${pct(limits['max_drawdown'] as num?, decimals: 0)} depuis le plus haut'),
          _Rule('Positions simultanées', '${limits['max_positions']} maximum'),
          Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text('Décisions du gardien', style: text.titleMedium)),
          if (events.isEmpty) const ListTile(title: Text('Aucune décision pour l\'instant.')),
          ...events.take(50).map((e) => ListTile(
                dense: true,
                leading: Icon(
                  e['kind'] == 'ORDER_APPROVED' ? Icons.check : (e['kind'] == 'HALT' ? Icons.stop_circle : Icons.info_outline),
                  color: e['kind'] == 'ORDER_APPROVED' ? okColor : (e['kind'] == 'HALT' ? dangerColor : null),
                ),
                title: Text('${e['detail']}'),
                subtitle: Text('${e['kind']} · ${shortDate(e['time'] as String?)}'),
              )),
        ]);
      },
    );
  }

  Future<void> _emergency(BuildContext context, Future<void> Function() reload) async {
    var exitAll = false;
    final go = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          title: const Text('Arrêt d\'urgence'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('Le bot n\'ouvrira plus aucune position. Le redémarrage exigera ton mot de passe.'),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: exitAll,
              onChanged: (v) => setState(() => exitAll = v ?? false),
              title: const Text('Vendre aussi toutes les positions ouvertes'),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: dangerColor),
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('ARRÊTER'),
            ),
          ],
        ),
      ),
    );
    if (go != true) return;
    try {
      final r = await api.post('/risk/emergency-stop', {'exit_all': exitAll}) as Map<String, dynamic>;
      if (context.mounted) await showMessage(context, (r['notes'] as List).join(' '));
    } on ApiException catch (e) {
      if (context.mounted) await showMessage(context, 'ÉCHEC : ${e.message}. Agis directement sur Binance.');
    }
    reload();
  }

  Future<void> _reset(BuildContext context, String phrase, Future<void> Function() reload) async {
    if (!await Biometrics().unlock('Confirme le redémarrage')) return;
    if (!context.mounted) return;
    final password = TextEditingController();
    final typed = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Redémarrer le système'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('As-tu compris pourquoi le système s\'est arrêté ? Ne redémarre pas pour « te refaire ».'),
          const SizedBox(height: 12),
          TextField(controller: password, obscureText: true, decoration: const InputDecoration(labelText: 'Mot de passe')),
          const SizedBox(height: 12),
          Text('Tape exactement : $phrase'),
          TextField(controller: typed),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Redémarrer')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await api.post('/risk/reset', {'password': password.text, 'confirmation': typed.text});
      if (context.mounted) await showMessage(context, 'Système redémarré.');
    } on ApiException catch (e) {
      if (context.mounted) await showMessage(context, e.message);
    }
    reload();
  }
}

class _Rule extends StatelessWidget {
  const _Rule(this.label, this.value);
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => ListTile(dense: true, title: Text(label), trailing: Text(value));
}
