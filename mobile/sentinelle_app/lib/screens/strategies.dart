import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import '../security.dart';
import '../theme.dart';
import 'home.dart';

class StrategiesScreen extends StatelessWidget {
  const StrategiesScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return AsyncPage<List<dynamic>>(
      load: api.strategies,
      builder: (context, list, reload) {
        final items = list.cast<Map<String, dynamic>>();
        final validated = items.where((s) => s['decision'] == 'PAPER_TRADING_ONLY').length;
        return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              '${items.length} stratégies étudiées par les agents · $validated validées.\n'
              'Rejeter la plupart des idées est normal : c\'est ce qui protège ton capital.',
            ),
          ),
          if (items.isEmpty) const ListTile(title: Text('Aucune recherche pour l\'instant.')),
          ...items.map((s) {
            final ok = s['decision'] == 'PAPER_TRADING_ONLY';
            return Card(
              child: ListTile(
                leading: Icon(ok ? Icons.check_circle : Icons.cancel, color: ok ? okColor : dangerColor),
                title: Text('${s['name']}'),
                subtitle: Text('${s['asset']} ${s['timeframe']} · ${decisionLabel(s['decision'] as String?)}'
                    '${s['approval'] != null ? ' · APPROUVÉE' : (s['paper_started_at'] != null ? ' · simulation J${s['paper_days']}' : '')}'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  await Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => StrategyDetailScreen(api: api, name: s['name'] as String),
                  ));
                  reload();
                },
              ),
            );
          }),
        ]);
      },
    );
  }
}

class StrategyDetailScreen extends StatelessWidget {
  const StrategyDetailScreen({super.key, required this.api, required this.name});
  final ApiClient api;
  final String name;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(name)),
      body: AsyncPage<Map<String, dynamic>>(
        load: () => api.strategy(name),
        builder: (context, s, reload) {
          final gates = (s['gates'] as Map).cast<String, dynamic>();
          final validated = s['decision'] == 'PAPER_TRADING_ONLY';
          final paperDays = s['paper_days'] as int? ?? 0;
          return ListView(padding: const EdgeInsets.all(16), children: [
            Text(decisionLabel(s['decision'] as String?), style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text('${s['reason']}'),
            const SizedBox(height: 12),
            Wrap(spacing: 8, children: [
              for (final g in ['gate1', 'gate2', 'gate3'])
                Chip(
                  avatar: Icon(gates[g] == 'PASS' ? Icons.check : (gates[g] == null ? Icons.remove : Icons.close), size: 18),
                  label: Text('${g.replaceAll('gate', 'Contrôle ')} : ${gates[g] ?? 'non atteint'}'),
                ),
            ]),
            const Divider(height: 32),
            if (validated && s['paper_started_at'] == null)
              FilledButton.icon(
                icon: const Icon(Icons.play_arrow),
                label: const Text('Démarrer la simulation (sans argent réel)'),
                onPressed: () async {
                  try {
                    await api.post('/strategies/$name/paper/start');
                    if (context.mounted) await showMessage(context, 'Simulation démarrée.');
                    reload();
                  } on ApiException catch (e) {
                    if (context.mounted) await showMessage(context, e.message);
                  }
                },
              ),
            if (validated && s['paper_started_at'] != null && s['approval'] == null) ...[
              LinearProgressIndicator(value: (paperDays / 28).clamp(0, 1).toDouble(), minHeight: 8),
              const SizedBox(height: 6),
              Text('Simulation : $paperDays / 28 jours minimum avant l\'argent réel.'),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                icon: const Icon(Icons.verified),
                label: const Text('Approuver pour le réel…'),
                onPressed: paperDays < 28 ? null : () => _approve(context, reload),
              ),
            ],
            if (s['approval'] != null)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.verified, color: okColor),
                  title: const Text('Approuvée pour le réel'),
                  subtitle: Text('${pct(s['approval']['capital_pct'] as num?, decimals: 0)} du capital · '
                      '${shortDate(s['approval']['time'] as String?)}'),
                ),
              ),
            const Divider(height: 32),
            Text('Rapport des agents', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            SelectableText(s['report_md'] as String? ?? ''),
          ]);
        },
      ),
    );
  }

  Future<void> _approve(BuildContext context, Future<void> Function() reload) async {
    if (!await Biometrics().unlock('Confirme l\'approbation de $name')) return;
    if (!context.mounted) return;
    final result = await showDialog<bool>(context: context, builder: (_) => _ApproveDialog(api: api, name: name));
    if (result == true) {
      if (context.mounted) await showMessage(context, 'Approuvée. Suis les étapes indiquées pour le passage en réel.');
      reload();
    }
  }
}

class _ApproveDialog extends StatefulWidget {
  const _ApproveDialog({required this.api, required this.name});
  final ApiClient api;
  final String name;
  @override
  State<_ApproveDialog> createState() => _ApproveDialogState();
}

class _ApproveDialogState extends State<_ApproveDialog> {
  final password = TextEditingController();
  final phrase = TextEditingController();
  double capital = 0.05;
  String? error;
  bool busy = false;

  String get expected => "J'APPROUVE ${widget.name}";

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Passage en argent réel'),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Le gardien reste actif : arrêt à −3 % sur la journée, arrêt complet à −10 %.'),
          const SizedBox(height: 12),
          Text('Part du capital allouée : ${pct(capital, decimals: 0)}'),
          Slider(value: capital, min: 0.01, max: 0.10, divisions: 9, onChanged: (v) => setState(() => capital = v)),
          TextField(controller: password, obscureText: true, decoration: const InputDecoration(labelText: 'Mot de passe')),
          const SizedBox(height: 12),
          Text('Tape exactement : $expected'),
          const SizedBox(height: 6),
          TextField(controller: phrase, decoration: const InputDecoration(labelText: 'Phrase de confirmation')),
          if (error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(error!, style: const TextStyle(color: dangerColor))),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Annuler')),
        FilledButton(
          onPressed: busy
              ? null
              : () async {
                  setState(() => busy = true);
                  try {
                    await widget.api.post('/strategies/${widget.name}/approve', {
                      'password': password.text,
                      'confirmation': phrase.text,
                      'capital_pct': double.parse(capital.toStringAsFixed(2)),
                    });
                    if (context.mounted) Navigator.pop(context, true);
                  } on ApiException catch (e) {
                    setState(() => error = e.message);
                  } finally {
                    if (mounted) setState(() => busy = false);
                  }
                },
          child: const Text('Approuver'),
        ),
      ],
    );
  }
}
