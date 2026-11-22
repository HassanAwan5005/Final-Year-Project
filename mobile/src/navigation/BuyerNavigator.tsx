import { Ionicons } from '@expo/vector-icons';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import React from 'react';

import { BookingDetailScreen } from '../features/bookings/screens/BookingDetailScreen';
import { BookingsScreen } from '../features/bookings/screens/BookingsScreen';
import { CreateBookingScreen } from '../features/bookings/screens/CreateBookingScreen';
import { ChatScreen } from '../features/chat/screens/ChatScreen';
import { ConversationsScreen } from '../features/chat/screens/ConversationsScreen';
import { NewChatScreen } from '../features/chat/screens/NewChatScreen';
import { ExploreScreen } from '../features/explore/screens/ExploreScreen';
import { HomeScreen } from '../features/explore/screens/HomeScreen';
import { NotificationSettingsScreen } from '../features/notifications/screens/NotificationSettingsScreen';
import { NotificationsScreen } from '../features/notifications/screens/NotificationsScreen';
import { MyReviewsScreen } from '../features/reviews/screens/MyReviewsScreen';
import { PhotographerReviewsScreen } from '../features/reviews/screens/PhotographerReviewsScreen';
import { WriteReviewScreen } from '../features/reviews/screens/WriteReviewScreen';
import { PhotographerDetailScreen } from '../features/photographer/screens/PhotographerDetailScreen';
import { EditProfileScreen } from '../features/profile/screens/EditProfileScreen';
import { ProfileScreen } from '../features/profile/screens/ProfileScreen';
import { VerifyEmailScreen } from '../features/auth/screens/VerifyEmailScreen';
import { WishlistScreen } from '../features/profile/screens/WishlistScreen';
import { EditProductScreen } from '../features/shop/screens/EditProductScreen';
import { ProductDetailScreen } from '../features/shop/screens/ProductDetailScreen';
import { PurchasesScreen } from '../features/shop/screens/PurchasesScreen';
import { SellerProductsScreen } from '../features/shop/screens/SellerProductsScreen';
import { SellProductScreen } from '../features/shop/screens/SellProductScreen';
import { ShopHomeScreen } from '../features/shop/screens/ShopHomeScreen';
import { ShopScreen } from '../features/shop/screens/ShopScreen';
import { colors } from '../theme';
import type { ProductReview, Review } from '../types/models';
import { useTabBarOptions } from './tabBarStyle';

export type BuyerTabParams = {
  Home: undefined;
  Explore: { category?: string } | undefined;
  Bookings: undefined;
  Shop: undefined;
  Profile: undefined;
};

/**
 * Detail, form and checkout screens live in a STACK ABOVE the tabs.
 *
 * If they were tab screens the bottom bar would stay visible and the sticky
 * action bars ("Book now", "Place order") would sit on top of it. Pushing
 * them over the whole tab navigator also means the same product or booking is
 * reachable from several tabs and always renders the same screen with a
 * working back button.
 */
export type BuyerStackParams = {
  Tabs: undefined;
  PhotographerDetail: { photographerId: number };
  CreateBooking: { photographerId: number; serviceId?: number };
  BookingDetail: { bookingId: number };
  ProductDetail: { slug: string };
  ShopBrowse: undefined;
  SellProduct: undefined;
  EditProduct: { productId: number };
  SellerProducts: undefined;
  Purchases: undefined;
  Wishlist: undefined;
  EditProfile: undefined;
  VerifyEmail: undefined;
  // ─── Module 9 ───────────────────────────────────────────────────────────
  MyReviews: undefined;
  PhotographerReviews: { photographerId: number; name?: string };
  /**
   * One screen for both kinds of review.
   *
   * The params carry the target plus the words to show above the form, so the
   * screen never has to fetch the booking or the order item again — the caller
   * already had it on screen.
   */
  WriteReview:
    | {
        kind: 'booking';
        bookingId: number;
        subject: string;
        detail?: string;
      }
    | {
        kind: 'product';
        orderItemId: number;
        subject: string;
        detail?: string;
      }
    | {
        kind: 'edit';
        review: Review;
        subject: string;
        detail?: string;
      }
    | {
        kind: 'editProduct';
        review: ProductReview;
        subject: string;
        detail?: string;
      };
  // ─── Modules 12 & 13 ────────────────────────────────────────────────────
  Notifications: undefined;
  NotificationSettings: undefined;
  Conversations: undefined;
  NewChat: undefined;
  /**
   * `conversationId: 0` plus `withUserId` means "open or find the thread with
   * this person" — the case the booking screen has, where a thread may not
   * exist yet.
   */
  Chat: {
    conversationId: number;
    withUserId?: number;
    bookingId?: number;
    productId?: number;
    title?: string;
  };
};

const Tab = createBottomTabNavigator<BuyerTabParams>();
const Stack = createNativeStackNavigator<BuyerStackParams>();

const ICONS: Record<keyof BuyerTabParams, keyof typeof Ionicons.glyphMap> = {
  Home: 'home',
  Explore: 'search',
  Bookings: 'calendar',
  Shop: 'bag-handle',
  Profile: 'person',
};

function BuyerTabs({ navigation }: any) {
  const tabBarOptions = useTabBarOptions();

  const openPhotographer = (photographerId: number) =>
    navigation.navigate('PhotographerDetail', { photographerId });
  const openBooking = (bookingId: number) =>
    navigation.navigate('BookingDetail', { bookingId });

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
      <Tab.Screen name="Home">
        {({ navigation: tabNav }) => (
          <HomeScreen
            onOpenPhotographer={openPhotographer}
            onOpenCategory={(category) => tabNav.navigate('Explore', { category })}
            onOpenSearch={() => tabNav.navigate('Explore')}
            onOpenNotifications={() => navigation.navigate('Notifications')}
            onOpenMessages={() => navigation.navigate('Conversations')}
          />
        )}
      </Tab.Screen>

      <Tab.Screen name="Explore">
        {({ route }) => (
          <ExploreScreen
            onOpenPhotographer={openPhotographer}
            initialCategory={route.params?.category}
          />
        )}
      </Tab.Screen>

      <Tab.Screen name="Bookings">
        {({ navigation: tabNav }) => (
          <BookingsScreen
            perspective="buyer"
            onOpenBooking={openBooking}
            onBrowse={() => tabNav.navigate('Explore')}
          />
        )}
      </Tab.Screen>

      <Tab.Screen name="Shop">
        {() => (
          <ShopHomeScreen
            onBuy={() => navigation.navigate('ShopBrowse')}
            onSell={() => navigation.navigate('SellProduct')}
            onOpenMyListings={() => navigation.navigate('SellerProducts')}
          />
        )}
      </Tab.Screen>

      <Tab.Screen name="Profile">
        {({ navigation: tabNav }) => (
          <ProfileScreen
            onOpenWishlist={() => navigation.navigate('Wishlist')}
            onOpenPurchases={() => navigation.navigate('Purchases')}
            onOpenBookings={() => tabNav.navigate('Bookings')}
            onOpenReviews={() => navigation.navigate('MyReviews')}
            onOpenMessages={() => navigation.navigate('Conversations')}
            onOpenNotifications={() => navigation.navigate('Notifications')}
            onOpenNotificationSettings={() =>
              navigation.navigate('NotificationSettings')
            }
            onEditProfile={() => navigation.navigate('EditProfile')}
            onVerifyEmail={() => navigation.navigate('VerifyEmail')}
          />
        )}
      </Tab.Screen>
    </Tab.Navigator>
  );
}

export function BuyerNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.bg },
        animation: 'slide_from_right',
      }}
    >
      <Stack.Screen name="Tabs" component={BuyerTabs} />

      {/* ─── Booking flow ────────────────────────────────────────────────── */}
      <Stack.Screen name="PhotographerDetail">
        {({ route, navigation }) => (
          <PhotographerDetailScreen
            photographerId={route.params.photographerId}
            onBack={() => navigation.goBack()}
            onBook={(serviceId) =>
              navigation.navigate('CreateBooking', {
                photographerId: route.params.photographerId,
                serviceId,
              })
            }
            onOpenReviews={(name) =>
              navigation.navigate('PhotographerReviews', {
                photographerId: route.params.photographerId,
                name,
              })
            }
            onWriteReview={(pending) =>
              navigation.navigate('WriteReview', {
                kind: 'booking',
                bookingId: pending.booking_id,
                subject: pending.photographer_name,
                detail: `${pending.service_name} · ${pending.event_date}`,
              })
            }
            onMessage={(userId, name) =>
              navigation.navigate('Chat', {
                conversationId: 0,
                withUserId: userId,
                title: name,
              })
            }
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="PhotographerReviews">
        {({ route, navigation }) => (
          <PhotographerReviewsScreen
            photographerId={route.params.photographerId}
            name={route.params.name}
            onBack={() => navigation.goBack()}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="CreateBooking">
        {({ route, navigation }) => (
          <CreateBookingScreen
            photographerId={route.params.photographerId}
            initialServiceId={route.params.serviceId}
            onBack={() => navigation.goBack()}
            // `replace`, not `navigate`: once the request is sent, backing up
            // into a form that would create a second booking is exactly the
            // mistake the Idempotency-Key exists to catch. Better not to
            // offer the route at all.
            onCreated={(bookingId) => navigation.replace('BookingDetail', { bookingId })}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="BookingDetail">
        {({ route, navigation }) => (
          <BookingDetailScreen
            bookingId={route.params.bookingId}
            perspective="buyer"
            onBack={() =>
              navigation.canGoBack() ? navigation.goBack() : navigation.navigate('Tabs')
            }
            onWriteReview={(booking) =>
              navigation.navigate('WriteReview', {
                kind: 'booking',
                bookingId: booking.id,
                subject: booking.photographer.name,
                detail: `${booking.service_title} · ${booking.event_date}`,
              })
            }
            // conversationId 0 means "resolve it": ChatScreen opens or finds the
            // thread with this photographer, attaching the booking to it.
            onOpenChat={(booking) =>
              navigation.navigate('Chat', {
                conversationId: 0,
                withUserId: booking.photographer.user_id,
                bookingId: booking.id,
                title: booking.photographer.name,
              })
            }
          />
        )}
      </Stack.Screen>

      {/* ─── Shop flow ───────────────────────────────────────────────────── */}
      <Stack.Screen name="ProductDetail">
        {({ route, navigation }) => (
          <ProductDetailScreen
            slug={route.params.slug}
            onBack={() => navigation.goBack()}
            onMessageSeller={(product) =>
              navigation.navigate('Chat', {
                conversationId: 0,
                withUserId: product.seller.id,
                productId: product.id,
                title: product.seller.display_name,
              })
            }
            onEdit={(productId) => navigation.navigate('EditProduct', { productId })}
          />
        )}
      </Stack.Screen>

      {/* ─── Shop: Buy / Sell ────────────────────────────────────────────── */}
      <Stack.Screen name="ShopBrowse">
        {({ navigation }) => (
          <ShopScreen
            onBack={() => navigation.goBack()}
            onOpenProduct={(slug) => navigation.navigate('ProductDetail', { slug })}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="SellProduct">
        {({ navigation }) => (
          <SellProductScreen
            onBack={() => navigation.goBack()}
            onSubmitted={() => navigation.replace('SellerProducts')}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="SellerProducts">
        {({ navigation }) => (
          <SellerProductsScreen
            onBack={() => navigation.goBack()}
            onOpenProduct={(slug) => navigation.navigate('ProductDetail', { slug })}
            onEditProduct={(productId) => navigation.navigate('EditProduct', { productId })}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="EditProduct">
        {({ route, navigation }) => (
          <EditProductScreen
            productId={route.params.productId}
            onBack={() => navigation.goBack()}
            onSaved={() => navigation.goBack()}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="Purchases">
        {({ navigation }) => (
          <PurchasesScreen
            onBack={() => navigation.goBack()}
            onWriteReview={(item) =>
              navigation.navigate('WriteReview', {
                kind: 'product',
                orderItemId: item.id,
                subject: item.product_title,
                detail: `Sold by ${item.seller_name}`,
              })
            }
          />
        )}
      </Stack.Screen>

      {/* ─── Profile flow ────────────────────────────────────────────────── */}
      <Stack.Screen name="Wishlist">
        {({ navigation }) => (
          <WishlistScreen
            onBack={() => navigation.goBack()}
            onOpenPhotographer={(photographerId) =>
              navigation.navigate('PhotographerDetail', { photographerId })
            }
            onOpenProduct={(slug) => navigation.navigate('ProductDetail', { slug })}
          />
        )}
      </Stack.Screen>

      {/* ─── Module 9 — reviews ──────────────────────────────────────────── */}
      <Stack.Screen name="MyReviews">
        {({ navigation }) => (
          <MyReviewsScreen
            onBack={() => navigation.goBack()}
            onWriteBookingReview={(target) =>
              navigation.navigate('WriteReview', {
                kind: 'booking',
                bookingId: target.booking_id,
                subject: target.photographer_name,
                detail: `${target.service_name} · ${target.event_date}`,
              })
            }
            onWriteProductReview={(target) =>
              navigation.navigate('WriteReview', {
                kind: 'product',
                orderItemId: target.order_item_id,
                subject: target.product_title,
              })
            }
            onEditReview={(review) =>
              navigation.navigate('WriteReview', {
                kind: 'edit',
                review,
                subject: review.photographer_name,
                detail: review.service_name,
              })
            }
            onEditProductReview={(review) =>
              navigation.navigate('WriteReview', {
                kind: 'editProduct',
                review,
                subject: review.product_title,
              })
            }
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="WriteReview">
        {({ route, navigation }) => (
          <WriteReviewScreen
            target={route.params}
            onBack={() => navigation.goBack()}
            // `goBack`, not `replace`: the buyer came from a booking or from the
            // reviews list, and both are now correct — the mutation invalidated
            // them. Pushing a new screen would strand them one level deeper.
            onDone={() => navigation.goBack()}
          />
        )}
      </Stack.Screen>

      {/* ─── Modules 12 & 13 — notifications and chat ────────────────────── */}
      <Stack.Screen name="Notifications">
        {({ navigation }) => (
          <NotificationsScreen
            onBack={() => navigation.goBack()}
            onOpenBooking={(bookingId) =>
              navigation.navigate('BookingDetail', { bookingId })
            }
            onOpenChat={(conversationId) =>
              navigation.navigate('Chat', { conversationId })
            }
            onOpenReviews={() => navigation.navigate('MyReviews')}
            onOpenProduct={(slug) => navigation.navigate('ProductDetail', { slug })}
            onOpenPreferences={() => navigation.navigate('NotificationSettings')}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="NotificationSettings">
        {({ navigation }) => (
          <NotificationSettingsScreen onBack={() => navigation.goBack()} />
        )}
      </Stack.Screen>

      <Stack.Screen name="Conversations">
        {({ navigation }) => (
          <ConversationsScreen
            onBack={() => navigation.goBack()}
            onOpenThread={(conversationId, title) =>
              navigation.navigate('Chat', { conversationId, title })
            }
            onNewMessage={() => navigation.navigate('NewChat')}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="NewChat">
        {({ navigation }) => (
          <NewChatScreen
            onBack={() => navigation.goBack()}
            // `replace`: backing up from a thread into the picker that opened it
            // would offer to open the same thread again.
            onOpenThread={(conversationId, title) =>
              navigation.replace('Chat', { conversationId, title })
            }
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="Chat">
        {({ route, navigation }) => (
          <ChatScreen
            conversationId={route.params.conversationId}
            startWith={
              route.params.withUserId
                ? {
                    userId: route.params.withUserId,
                    bookingId: route.params.bookingId,
                    productId: route.params.productId,
                  }
                : undefined
            }
            title={route.params.title}
            onBack={() => navigation.goBack()}
            onOpenBooking={(bookingId) =>
              navigation.navigate('BookingDetail', { bookingId })
            }
            onOpenProduct={(slug) => navigation.navigate('ProductDetail', { slug })}
          />
        )}
      </Stack.Screen>

      <Stack.Screen name="EditProfile">
        {({ navigation }) => <EditProfileScreen onBack={() => navigation.goBack()} />}
      </Stack.Screen>

      <Stack.Screen name="VerifyEmail">
        {({ navigation }) => (
          <VerifyEmailScreen
            codeAlreadySent={false}
            closeLabel="Back to profile"
            onClose={() => navigation.goBack()}
          />
        )}
      </Stack.Screen>
    </Stack.Navigator>
  );
}
