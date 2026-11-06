import { Image } from 'expo-image';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { FormScreen } from '@/components/screen';
import { Button, Field, Notice, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useForm } from '@/lib/form';
import { colors, space } from '@/lib/theme';
import { useAuth } from '@/state/auth';

export default function SignInScreen() {
  const { signIn } = useAuth();
  const [registering, setRegistering] = useState(false);
  const [created, setCreated] = useState('');

  const loginForm = useForm({
    username: '',
    password: '',
  });

  const registerForm = useForm({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    username: '',
    password: '',
    password_confirm: '',
  });

  const submitLogin = () =>
    loginForm.submit(
      () =>
        api.login(
          loginForm.values.username.trim(),
          loginForm.values.password,
        ),
      ({ token, user }) => void signIn(token, user),
    );

  const submitRegister = () =>
    registerForm.submit(
      () =>
        api.register(
          registerForm.values.username.trim(),
          registerForm.values.email.trim(),
          registerForm.values.first_name.trim(),
          registerForm.values.last_name.trim(),
          registerForm.values.phone.trim(),
          registerForm.values.password,
          registerForm.values.password_confirm,
        ),
      ({ message, username }) => {
        // Back to the sign-in screen: new accounts sign in like everyone else.
        setCreated(message);
        loginForm.set('username', username);
        loginForm.set('password', '');
        registerForm.set('password', '');
        registerForm.set('password_confirm', '');
        setRegistering(false);
      },
    );

  if (registering) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }}>
        <FormScreen style={{ justifyContent: 'center', flexGrow: 1 }}>
          <View style={styles.hero}>
            <Image
              source={require('../../assets/logo.png')}
              style={{ width: 72, height: 72 }}
            />

            <T variant="title">Create Fleet Account</T>

            <T style={{ color: colors.muted, textAlign: 'center' }}>
              The office approves new accounts. You can sign in once they have.
            </T>
          </View>

          {registerForm.error && (
            <Notice tone="danger">
              {registerForm.error.message}
            </Notice>
          )}

          <Field
            label="First name"
            autoCapitalize="words"
            {...registerForm.bind('first_name')}
          />

          <Field
            label="Last name"
            autoCapitalize="words"
            {...registerForm.bind('last_name')}
          />

          <Field
            label="Email"
            autoCapitalize="none"
            keyboardType="email-address"
            {...registerForm.bind('email')}
          />

          <Field
            label="Phone"
            keyboardType="phone-pad"
            {...registerForm.bind('phone')}
          />

          <Field
            label="Username"
            autoCapitalize="none"
            {...registerForm.bind('username')}
          />

          <Field
            label="Password"
            secure
            {...registerForm.bind('password')}
          />

          <Field
            label="Confirm password"
            secure
            onSubmitEditing={submitRegister}
            {...registerForm.bind('password_confirm')}
          />

          <Button
            title="Create Account"
            onPress={submitRegister}
            loading={registerForm.busy}
            disabled={
              !registerForm.values.first_name ||
              !registerForm.values.last_name ||
              !registerForm.values.email ||
              !registerForm.values.username ||
              !registerForm.values.password ||
              !registerForm.values.password_confirm
            }
          />

          <Button
            title="Back to Sign In"
            onPress={() => setRegistering(false)}
          />
        </FormScreen>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }}>
      <FormScreen style={{ justifyContent: 'center', flexGrow: 1 }}>
        <View style={styles.hero}>
          <Image
            source={require('../../assets/logo.png')}
            style={{ width: 72, height: 72 }}
          />

          <T variant="title">Mahitaji Fleet</T>

          <T style={{ color: colors.muted, textAlign: 'center' }}>
            Vehicles, drivers and turnboys, delivery areas and customers.
            Sign in with your Mahitaji staff account.
          </T>
        </View>

        {loginForm.error ? (
          <Notice tone="danger">
            {loginForm.error.message}
          </Notice>
        ) : created ? (
          <Notice tone="success">
            {created}
          </Notice>
        ) : null}

        <Field
          label="Email or username"
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          textContentType="username"
          {...loginForm.bind('username')}
        />

        <Field
          label="Password"
          secure
          autoComplete="password"
          textContentType="password"
          onSubmitEditing={submitLogin}
          {...loginForm.bind('password')}
        />

        <Button
          title="Sign in"
          onPress={submitLogin}
          loading={loginForm.busy}
          disabled={
            !loginForm.values.username ||
            !loginForm.values.password
          }
        />

        <Button
          title="Create Account"
          onPress={() => {
            setCreated('');
            setRegistering(true);
          }}
        />

        <T variant="caption" style={{ textAlign: 'center' }}>
          New to Mahitaji Fleet? Create an account, and the office will approve it.
        </T>
      </FormScreen>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  hero: {
    alignItems: 'center',
    gap: space.sm,
    marginBottom: space.md,
  },
});
