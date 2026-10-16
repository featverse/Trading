import 'package:flutter/material.dart';

import '../api.dart';
import 'dashboard.dart';
import 'more.dart';
import 'positions.dart';
import 'risk.dart';
import 'strategies.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.api, required this.onLoggedOut});
  final ApiClient api;
  final VoidCallback onLoggedOut;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int index = 0;

  @override
  Widget build(BuildContext context) {
    final pages = [
      DashboardScreen(api: widget.api),
      PositionsScreen(api: widget.api),
      StrategiesScreen(api: widget.api),
      RiskScreen(api: widget.api),
      MoreScreen(api: widget.api, onLoggedOut: widget.onLoggedOut),
    ];
    return Scaffold(
      body: SafeArea(child: IndexedStack(index: index, children: pages)),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => setState(() => index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Accueil'),
          NavigationDestination(icon: Icon(Icons.show_chart), label: 'Positions'),
          NavigationDestination(icon: Icon(Icons.science_outlined), selectedIcon: Icon(Icons.science), label: 'Agents'),
          NavigationDestination(icon: Icon(Icons.shield_outlined), selectedIcon: Icon(Icons.shield), label: 'Risque'),
          NavigationDestination(icon: Icon(Icons.more_horiz), label: 'Plus'),
        ],
      ),
    );
  }
}

/// Petit utilitaire partagé : charge des données avec tirer-pour-actualiser et erreurs lisibles.
class AsyncPage<T> extends StatefulWidget {
  const AsyncPage({super.key, required this.load, required this.builder, this.refreshEvery});
  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;
  final Duration? refreshEvery;

  @override
  State<AsyncPage<T>> createState() => _AsyncPageState<T>();
}

class _AsyncPageState<T> extends State<AsyncPage<T>> {
  T? data;
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _reload();
    final every = widget.refreshEvery;
    if (every != null) {
      Future.doWhile(() async {
        await Future.delayed(every);
        if (!mounted) return false;
        await _reload(silent: true);
        return mounted;
      });
    }
  }

  Future<void> _reload({bool silent = false}) async {
    if (!silent) setState(() => loading = true);
    try {
      final d = await widget.load();
      if (mounted) {
        setState(() {
          data = d;
          error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (data == null) {
      return Center(
        child: loading
            ? const CircularProgressIndicator()
            : Column(mainAxisSize: MainAxisSize.min, children: [
                Text(error ?? 'Aucune donnée'),
                const SizedBox(height: 12),
                OutlinedButton(onPressed: _reload, child: const Text('Réessayer')),
              ]),
      );
    }
    return RefreshIndicator(
      onRefresh: _reload,
      child: Column(children: [
        if (error != null)
          MaterialBanner(content: Text('Données peut-être anciennes : $error'), actions: [
            TextButton(onPressed: _reload, child: const Text('Actualiser')),
          ]),
        Expanded(child: widget.builder(context, data as T, _reload)),
      ]),
    );
  }
}

Future<void> showMessage(BuildContext context, String text) async {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
}
