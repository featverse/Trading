import 'package:flutter/material.dart';

import '../api.dart';
import '../security.dart';

/// Première connexion : adresse HTTPS du serveur + mot de passe.
/// Le mot de passe n'est JAMAIS enregistré sur le téléphone.
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key, required this.store, required this.onReady});
  final SecureStore store;
  final void Function(ApiClient client) onReady;

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  final server = TextEditingController(text: 'https://');
  final password = TextEditingController();
  bool busy = false;
  String? error;

  @override
  void initState() {
    super.initState();
    widget.store.readServer().then((s) {
      if (s != null && mounted) server.text = s;
    });
  }

  Future<void> _connect() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final client = ApiClient(baseUrl: server.text, tokens: widget.store);
      await client.login(password.text);
      await widget.store.writeServer(server.text.trim());
      password.clear();
      widget.onReady(client);
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } catch (_) {
      setState(() => error = 'Connexion impossible.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(24), children: [
          const SizedBox(height: 32),
          Icon(Icons.shield_outlined, size: 56, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 12),
          Text('Sentinelle', textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 4),
          const Text('Le capital d\'abord, la performance ensuite.', textAlign: TextAlign.center),
          const SizedBox(height: 32),
          TextField(
            controller: server,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(labelText: 'Adresse du serveur', hintText: 'https://monbot.duckdns.org'),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: password,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Mot de passe'),
            onSubmitted: (_) => _connect(),
          ),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 24),
          FilledButton(
            onPressed: busy ? null : _connect,
            child: busy
                ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Se connecter'),
          ),
          const SizedBox(height: 24),
          const Text(
            'Le mot de passe n\'est pas enregistré. Ensuite, l\'application s\'ouvre avec ton empreinte.',
            textAlign: TextAlign.center,
          ),
        ]),
      ),
    );
  }
}
