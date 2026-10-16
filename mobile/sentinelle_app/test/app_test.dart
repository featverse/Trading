import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sentinelle_app/api.dart';
import 'package:sentinelle_app/format.dart';
import 'package:sentinelle_app/screens/dashboard.dart';
import 'package:sentinelle_app/screens/risk.dart';

class MemoryTokens implements TokenStore {
  String? token;
  @override
  Future<String?> readRefreshToken() async => token;
  @override
  Future<void> writeRefreshToken(String? t) async => token = t;
}

http.Response json(Object body, [int code = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), code, headers: {'content-type': 'application/json'});

final statusBody = {
  'status': 'ACTIVE',
  'halt_reason': null,
  'equity_usdt': 100.0,
  'equity_fcfa': 60000.0,
  'drawdown': -0.02,
  'day_change': 0.004,
  'consecutive_losses': 1,
  'current_risk_pct': 0.005,
  'tier': {'name': 'P1', 'description': 'Réel, risque 0,5 %', 'live_trading': true},
  'next_milestone_fcfa': 100000.0,
  'milestone_progress': 0.6,
  'total_secured_fcfa': 0.0,
  'feed': {'ok': true},
  'plan': {
    'monthly_deposit_fcfa': 20000,
    'months_to_100k': {'0%': 2, '2%': 2},
    'months_to_1m': {'0%': 47, '2%': 34},
  },
  'disclaimer': 'Illustratif, pas un conseil financier. Aucune garantie de performance.',
};

void main() {
  group('format', () {
    test('fcfa groups thousands', () {
      expect(fcfa(1000000), '1 000 000 FCFA');
      expect(fcfa(-2500), '−2 500 FCFA');
      expect(fcfa(null), '—');
    });
    test('pct', () {
      expect(pct(-0.031), '−3,1 %');
      expect(pct(0.02, signed: true), '+2,0 %');
    });
    test('labels', () {
      expect(statusLabel('HALTED'), 'Arrêt de sécurité');
      expect(decisionLabel('REJECTED'), 'Rejetée');
    });
  });

  group('ApiClient', () {
    test('refuses plain http to a remote host', () {
      expect(() => ApiClient(baseUrl: 'http://monbot.example.com', tokens: MemoryTokens()), throwsA(isA<ApiException>()));
    });

    test('login then refresh-on-401 retries once', () async {
      final tokens = MemoryTokens();
      var statusCalls = 0;
      final mock = MockClient((req) async {
        switch (req.url.path) {
          case '/auth/login':
            return json({'access_token': 'a1', 'refresh_token': 'r1', 'expires_in': 900});
          case '/auth/refresh':
            expect(jsonDecode(req.body)['refresh_token'], 'r1');
            return json({'access_token': 'a2', 'refresh_token': 'r2', 'expires_in': 900});
          case '/status':
            statusCalls++;
            if (req.headers['Authorization'] == 'Bearer a1') return json({'detail': 'Jeton expiré.'}, 401);
            return json(statusBody);
        }
        return json({'detail': 'inconnu'}, 404);
      });
      final api = ApiClient(baseUrl: 'https://bot.example.com', tokens: tokens, httpClient: mock);
      await api.login('secret');
      final s = await api.status();
      expect(s['status'], 'ACTIVE');
      expect(statusCalls, 2);
      expect(tokens.token, 'r2'); // rotation enregistrée
    });

    test('failed refresh clears the session and surfaces the error', () async {
      final tokens = MemoryTokens()..token = 'vieux';
      final mock = MockClient((req) async => req.url.path == '/auth/refresh'
          ? json({'detail': 'Session révoquée.'}, 401)
          : json({'detail': 'Authentification requise.'}, 401));
      final api = ApiClient(baseUrl: 'https://bot.example.com', tokens: tokens, httpClient: mock);
      await expectLater(api.status(), throwsA(isA<ApiException>().having((e) => e.statusCode, 'code', 401)));
      expect(tokens.token, isNull);
    });

    test('server error message is shown in French', () async {
      final mock = MockClient((_) async => json({'detail': 'Mot de passe incorrect.'}, 401));
      final api = ApiClient(baseUrl: 'https://bot.example.com', tokens: MemoryTokens(), httpClient: mock);
      await expectLater(api.login('x'), throwsA(isA<ApiException>().having((e) => e.message, 'msg', 'Mot de passe incorrect.')));
    });
  });

  group('screens', () {
    ApiClient fakeApi(Map<String, Object> routes) => ApiClient(
          baseUrl: 'https://bot.example.com',
          tokens: MemoryTokens(),
          httpClient: MockClient((req) async => json(routes[req.url.path] ?? {'detail': 'x'}, routes.containsKey(req.url.path) ? 200 : 404)),
        );

    void tallScreen(WidgetTester tester) {
      tester.view.physicalSize = const Size(1080, 4000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
    }

    testWidgets('dashboard shows capital in FCFA, status and milestone', (tester) async {
      tallScreen(tester);
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: DashboardScreen(api: fakeApi({'/status': statusBody})))));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.text('Actif'), findsOneWidget);
      expect(find.text('60 000 FCFA'), findsOneWidget);
      expect(find.textContaining('Palier P1'), findsOneWidget);
      expect(find.textContaining('Aucune garantie'), findsOneWidget);
      await tester.pumpWidget(const SizedBox()); // arrête le rafraîchissement périodique
      await tester.pump(const Duration(seconds: 31));
    });

    testWidgets('risk screen shows the emergency button and fixed rules', (tester) async {
      tallScreen(tester);
      final risk = {
        'limits': {
          'spot_only': true,
          'max_leverage': 1,
          'risk_per_trade': 0.005,
          'max_position_pct': 0.2,
          'max_total_exposure': 0.6,
          'daily_loss_limit': 0.03,
          'max_drawdown': 0.1,
          'max_positions': 3,
        },
        'status': 'HALTED',
        'guard_events': [
          {'time': '2026-11-02T10:00:00+00:00', 'kind': 'HALT', 'detail': 'Drawdown -10,2 %'},
        ],
        'reset_confirmation': 'JE CONFIRME LE REDEMARRAGE',
      };
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: RiskScreen(api: fakeApi({'/risk': risk})))));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.text('ARRÊT D\'URGENCE'), findsOneWidget);
      expect(find.text('Spot uniquement, aucun levier'), findsOneWidget);
      expect(find.textContaining('Redémarrer'), findsOneWidget);
      expect(find.text('Drawdown -10,2 %'), findsOneWidget);
    });
  });
}
