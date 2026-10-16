import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/home.dart';
import 'screens/setup.dart';
import 'security.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SentinelleApp());
}

class SentinelleApp extends StatelessWidget {
  const SentinelleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sentinelle',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      home: const Gate(),
    );
  }
}

/// Porte d'entrée : configuration → déverrouillage biométrique → session.
class Gate extends StatefulWidget {
  const Gate({super.key});
  @override
  State<Gate> createState() => _GateState();
}

class _GateState extends State<Gate> {
  final store = SecureStore();
  final bio = Biometrics();
  ApiClient? api;
  String? error;
  bool busy = true;
  bool needsSetup = false;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    setState(() {
      busy = true;
      error = null;
    });
    final server = await store.readServer();
    final hasSession = await store.readRefreshToken() != null;
    if (server == null || !hasSession) {
      setState(() {
        needsSetup = true;
        busy = false;
      });
      return;
    }
    final ok = await bio.unlock('Déverrouille Sentinelle');
    if (!ok) {
      setState(() {
        error = 'Déverrouillage refusé.';
        busy = false;
      });
      return;
    }
    try {
      final client = ApiClient(baseUrl: server, tokens: store);
      if (await client.refresh()) {
        setState(() {
          api = client;
          busy = false;
        });
      } else {
        setState(() {
          needsSetup = true;
          busy = false;
        });
      }
    } on ApiException catch (e) {
      setState(() {
        error = e.message;
        busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (api != null) {
      return HomeScreen(
        api: api!,
        onLoggedOut: () => setState(() {
          api = null;
          needsSetup = true;
        }),
      );
    }
    if (needsSetup) {
      return SetupScreen(
        store: store,
        onReady: (client) => setState(() {
          api = client;
          needsSetup = false;
        }),
      );
    }
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: busy
              ? const CircularProgressIndicator()
              : Column(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.lock_outline, size: 48),
                  const SizedBox(height: 12),
                  Text(error ?? 'Verrouillé', textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _start, child: const Text('Réessayer')),
                ]),
        ),
      ),
    );
  }
}
