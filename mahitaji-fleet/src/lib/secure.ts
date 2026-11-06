import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * The sign-in token lives in the phone's keychain / keystore. Secure storage does not exist in
 * a browser, so the web preview (`npx expo start --web`) keeps it in localStorage instead.
 */
export const secure = {
  get: (key: string) =>
    Platform.OS === 'web' ? Promise.resolve(globalThis.localStorage?.getItem(key) ?? null) : SecureStore.getItemAsync(key),
  set: (key: string, value: string) =>
    Platform.OS === 'web' ? Promise.resolve(globalThis.localStorage?.setItem(key, value)) : SecureStore.setItemAsync(key, value),
  remove: (key: string) =>
    Platform.OS === 'web' ? Promise.resolve(globalThis.localStorage?.removeItem(key)) : SecureStore.deleteItemAsync(key),
};
