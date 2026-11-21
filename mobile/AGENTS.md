# Expo SDK 58

This project is on **Expo SDK 58** (`expo@^58.0.0`, React Native 0.88,
React 19.3).

Read the exact versioned docs at https://docs.expo.dev/versions/v58.0.0/
before writing any code. Do NOT follow documentation for other SDK versions —
APIs, config-plugin availability and package versions differ between SDKs.

## Running on a phone

Expo Go supports exactly one SDK version at a time. The test device must have
the **SDK 58** build of Expo Go; an older one fails with:

    ERROR  Project is incompatible with this version of Expo Go

Do not change the SDK (`npx expo install expo@<version>`) without first
confirming the Expo Go build on the test devices supports it.

The app finds the backend automatically from the address Expo serves the
bundle from. Set `EXPO_PUBLIC_API_URL` in `mobile/.env` only for a tunnel or a
backend on another machine — when set, it always wins.

## SDK 58 notes already handled here

* `expo-image` and `expo-status-bar` ship config plugins in SDK 58, so both
  are listed in `app.json` → `plugins`.
* `react-native-reanimated@4` requires `react-native-worklets` as a direct
  dependency **and** `react-native-worklets/plugin` as the last entry in
  `babel.config.js`.

## Version alignment

After changing any Expo package, run:

    npx expo install --check     # report drift
    npx expo install --fix       # realign to the SDK
    npx tsc --noEmit             # typecheck
