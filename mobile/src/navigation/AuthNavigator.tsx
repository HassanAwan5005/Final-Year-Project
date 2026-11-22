import { createNativeStackNavigator } from '@react-navigation/native-stack';
import React from 'react';

import { LoginScreen } from '../features/auth/screens/LoginScreen';
import { RegisterScreen } from '../features/auth/screens/RegisterScreen';
import { ForgotPasswordScreen } from '../features/auth/screens/ForgotPasswordScreen';
import { colors } from '../theme';

export type AuthStackParams = {
  /** `email` is the account that was just created or had its password reset. */
  Login: { email?: string } | undefined;
  Register: undefined;
  ForgotPassword: undefined;
};

const Stack = createNativeStackNavigator<AuthStackParams>();

export function AuthNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.bg },
        animation: 'slide_from_right',
      }}
    >
      <Stack.Screen name="Login">
        {({ navigation, route }) => (
          <LoginScreen
            resetEmail={route.params?.email}
            onGoRegister={() => navigation.navigate('Register')}
            onGoForgot={() => navigation.navigate('ForgotPassword')}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="Register">
        {({ navigation }) => (
          <RegisterScreen
            onGoLogin={() => navigation.goBack()}
            onRegistered={(email) => navigation.popTo('Login', { email })}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="ForgotPassword">
        {({ navigation }) => (
          <ForgotPasswordScreen
            onGoLogin={() => navigation.goBack()}
            onResetDone={(email) => navigation.popTo('Login', { email })}
          />
        )}
      </Stack.Screen>
    </Stack.Navigator>
  );
}
