import { createNativeStackNavigator } from '@react-navigation/native-stack';
import React from 'react';

import { PendingListingsScreen } from '../features/admin/screens/PendingListingsScreen';

/**
 * What an ADMIN account sees after signing in on the normal login screen.
 *
 * Deliberately small: the moderation queue for products submitted from the
 * Shop → Sell form. Every action is re-checked on the server, which only
 * accepts it from an ADMIN account.
 */
export type AdminStackParams = {
  PendingListings: undefined;
};

const Stack = createNativeStackNavigator<AdminStackParams>();

export function AdminNavigator() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="PendingListings" component={PendingListingsScreen} />
    </Stack.Navigator>
  );
}
