import 'package:flutter/material.dart';

import '../api.dart';
import '../format.dart';
import 'home.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key, required this.api, required this.onLoggedOut});
  final ApiClient api;
  final VoidCallback onLoggedOut;

  @override
  Widget build(BuildContext context) {
    return ListView(children: [
      ListTile(
        leading: const Icon(Icons.savings_outlined),
        title: const Text('Mes apports (plan d\'épargne)'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => DepositsScreen(api: api))),
      ),
      ListTile(
        leading: const Icon(Icons.history),
        title: const Text('Journal du système'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => EventsScreen(api: api))),
      ),
      const Divider(),
      ListTile(
        leading: const Icon(Icons.logout),
        title: const Text('Déconnecter tous les appareils'),
        subtitle: const Text('À faire si ton téléphone est perdu ou volé (depuis un autre appareil).'),
        onTap: () async {
          try {
            await api.logoutEverywhere();
          } on ApiException catch (_) {}
          onLoggedOut();
        },
      ),
      const Padding(
        padding: EdgeInsets.all(16),
        child: Text('Illustratif, pas un conseil financier. Aucune garantie de performance.', textAlign: TextAlign.center),
      ),
    ]);
  }
}

class DepositsScreen extends StatelessWidget {
  const DepositsScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mes apports')),
      body: AsyncPage<List<dynamic>>(
        load: api.deposits,
        builder: (context, list, reload) {
          final items = list.cast<Map<String, dynamic>>();
          final total = items.fold<num>(0, (s, d) => s + (d['amount_fcfa'] as num));
          return ListView(children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text('Total noté : ${fcfa(total)}\n'
                  'Note ici tes envois Mobile Money. Les mouvements réels sur Binance sont détectés '
                  'automatiquement par le serveur.'),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: FilledButton.icon(
                icon: const Icon(Icons.add),
                label: const Text('Noter un apport'),
                onPressed: () => _add(context, reload),
              ),
            ),
            ...items.reversed.map((d) => ListTile(
                  title: Text(fcfa(d['amount_fcfa'] as num?)),
                  subtitle: Text('${d['note']} · ${shortDate(d['time'] as String?)}'),
                )),
          ]);
        },
      ),
    );
  }

  Future<void> _add(BuildContext context, Future<void> Function() reload) async {
    final amount = TextEditingController(text: '20000');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Noter un apport'),
        content: TextField(
          controller: amount,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: 'Montant (FCFA)'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annuler')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Enregistrer')),
        ],
      ),
    );
    if (ok != true) return;
    final value = double.tryParse(amount.text.replaceAll(' ', ''));
    if (value == null || value <= 0) {
      if (context.mounted) await showMessage(context, 'Montant invalide.');
      return;
    }
    try {
      await api.post('/deposits', {'amount_fcfa': value, 'note': 'Mobile Money'});
    } on ApiException catch (e) {
      if (context.mounted) await showMessage(context, e.message);
    }
    reload();
  }
}

class EventsScreen extends StatelessWidget {
  const EventsScreen({super.key, required this.api});
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Journal du système')),
      body: AsyncPage<List<dynamic>>(
        load: api.events,
        builder: (context, list, reload) => ListView(
          children: list
              .cast<Map<String, dynamic>>()
              .map((e) => ListTile(
                    dense: true,
                    title: Text('${e['detail']}'),
                    subtitle: Text('${e['kind']} · ${shortDate(e['time'] as String?)}'),
                  ))
              .toList(),
        ),
      ),
    );
  }
}
