import { Ionicons } from '@expo/vector-icons';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import React from 'react';

import { AdminAuditLogScreen } from '../features/admin/screens/AdminAuditLogScreen';
import { AdminBookingDetailScreen } from '../features/admin/screens/AdminBookingDetailScreen';
import { AdminBookingsScreen } from '../features/admin/screens/AdminBookingsScreen';
import { AdminBroadcastsScreen } from '../features/admin/screens/AdminBroadcastsScreen';
import { AdminDashboardScreen } from '../features/admin/screens/AdminDashboardScreen';
import { AdminMoreScreen } from '../features/admin/screens/AdminMoreScreen';
import { AdminReportsScreen } from '../features/admin/screens/AdminReportsScreen';
import { AdminSettingsScreen } from '../features/admin/screens/AdminSettingsScreen';
import { AdminUserDetailScreen } from '../features/admin/screens/AdminUserDetailScreen';
import { AdminUsersScreen } from '../features/admin/screens/AdminUsersScreen';
import { useTabBarOptions } from './tabBarStyle';

/**
 * What an ADMIN account sees after signing in on the normal login screen.
 *
 * Five tabs: Dashboard · Users · Reports · Bookings · More (audit log,
 * settings, broadcasts, log out). Every action is re-checked on the server,
 * which only accepts it from an ADMIN account and writes it to the audit log.
 */
export type AdminTabParams = {
  Dashboard: undefined;
  Users: undefined;
  Reports: undefined;
  Bookings: undefined;
  More: undefined;
};

export type AdminStackParams = {
  Tabs: undefined;
  AdminUser: { userId: number };
  AdminBooking: { bookingId: number };
  AuditLog: undefined;
  PlatformSettings: undefined;
  Broadcasts: undefined;
};

const Tab = createBottomTabNavigator<AdminTabParams>();
const Stack = createNativeStackNavigator<AdminStackParams>();

const ICONS: Record<keyof AdminTabParams, keyof typeof Ionicons.glyphMap> = {
  Dashboard: 'stats-chart',
  Users: 'people',
  Reports: 'flag',
  Bookings: 'calendar',
  More: 'ellipsis-horizontal-circle',
};

function AdminTabs({ navigation }: any) {
  const tabBarOptions = useTabBarOptions();

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        ...tabBarOptions,
        tabBarIcon: ({ color, size, focused }) => (
          <Ionicons
            name={
              focused
                ? ICONS[route.name]
                : (`${ICONS[route.name]}-outline` as keyof typeof Ionicons.glyphMap)
            }
            size={size - 2}
            color={color}
          />
        ),
      })}
    >
      <Tab.Screen name="Dashboard">
        {({ navigation: tabs }) => (
          <AdminDashboardScreen
            onOpenReports={() => tabs.navigate('Reports')}
            onOpenUsers={() => tabs.navigate('Users')}
            onOpenBookings={() => tabs.navigate('Bookings')}
          />
        )}
      </Tab.Screen>
      <Tab.Screen name="Users">
        {() => (
          <AdminUsersScreen onOpenUser={(userId) => navigation.navigate('AdminUser', { userId })} />
        )}
      </Tab.Screen>
      <Tab.Screen name="Reports" component={AdminReportsScreen} />
      <Tab.Screen name="Bookings">
        {() => (
          <AdminBookingsScreen
            onOpenBooking={(bookingId) => navigation.navigate('AdminBooking', { bookingId })}
          />
        )}
      </Tab.Screen>
      <Tab.Screen name="More">
        {() => (
          <AdminMoreScreen
            onOpenAudit={() => navigation.navigate('AuditLog')}
            onOpenSettings={() => navigation.navigate('PlatformSettings')}
            onOpenBroadcasts={() => navigation.navigate('Broadcasts')}
          />
        )}
      </Tab.Screen>
    </Tab.Navigator>
  );
}

export function AdminNavigator() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="Tabs" component={AdminTabs} />
      <Stack.Screen name="AdminUser">
        {({ route, navigation }) => (
          <AdminUserDetailScreen userId={route.params.userId} onBack={() => navigation.goBack()} />
        )}
      </Stack.Screen>
      <Stack.Screen name="AdminBooking">
        {({ route, navigation }) => (
          <AdminBookingDetailScreen
            bookingId={route.params.bookingId}
            onBack={() => navigation.goBack()}
            onOpenUser={(userId) => navigation.push('AdminUser', { userId })}
          />
        )}
      </Stack.Screen>
      <Stack.Screen name="AuditLog">
        {({ navigation }) => <AdminAuditLogScreen onBack={() => navigation.goBack()} />}
      </Stack.Screen>
      <Stack.Screen name="PlatformSettings">
        {({ navigation }) => <AdminSettingsScreen onBack={() => navigation.goBack()} />}
      </Stack.Screen>
      <Stack.Screen name="Broadcasts">
        {({ navigation }) => <AdminBroadcastsScreen onBack={() => navigation.goBack()} />}
      </Stack.Screen>
    </Stack.Navigator>
  );
}
