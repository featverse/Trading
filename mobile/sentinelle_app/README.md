# Sentinelle — application Android

Tour de contrôle de l'IA de trading : capital en FCFA, paliers, positions, agents, gardien et arrêt d'urgence.

- Déverrouillage par empreinte / visage ; jeton de session chiffré dans le Keystore Android.
- Mot de passe jamais enregistré sur le téléphone ; HTTPS obligatoire.
- APK compilé automatiquement par GitHub Actions (artefact `sentinelle-android-apk`).

```bash
flutter pub get && flutter analyze && flutter test
flutter build apk --release
```
