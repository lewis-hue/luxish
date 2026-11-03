import type { ExpoConfig } from 'expo/config';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const brand = require('./branding.config.js');

/**
 * Replaces the static app.json so product identity comes from one module (ADR-002).
 * Permission strings are declared here, at the point of use, because both stores
 * reject builds whose usage descriptions do not explain the actual purpose (§13).
 */
const config: ExpoConfig = {
  name: brand.name,
  slug: brand.slug,
  // The EAS account that owns the project below. Written here rather
  // than left to the CLI because this is a dynamic config, which
  // `eas init` cannot edit for us.
  owner: 'lew2434',
  scheme: brand.scheme,
  version: '1.0.0',
  orientation: 'portrait',
  icon: './assets/images/icon.png',
  userInterfaceStyle: 'automatic',

  ios: {
    icon: './assets/expo.icon',
    bundleIdentifier: brand.ids.iosBundle,
    // Short, specific reasons — generic strings are a common review rejection.
    infoPlist: {
      NSCameraUsageDescription:
        'Take photos of your clothes to add them to your wardrobe.',
      NSPhotoLibraryUsageDescription:
        'Choose existing photos of your clothes to add them to your wardrobe.',
      NSMicrophoneUsageDescription:
        'Describe an outfit to the stylist by speaking instead of typing.',
      NSLocationWhenInUseUsageDescription:
        'Suggest outfits for your local weather and show retailers that deliver to you.',
    },
  },

  android: {
    package: brand.ids.androidPackage,
    adaptiveIcon: {
      backgroundColor: '#FAF7F2',
      foregroundImage: './assets/images/android-icon-foreground.png',
      backgroundImage: './assets/images/android-icon-background.png',
      monochromeImage: './assets/images/android-icon-monochrome.png',
    },
    predictiveBackGestureEnabled: false,
  },

  web: {
    output: 'server',
    favicon: './assets/images/favicon.png',
  },

  plugins: [
    'expo-router',
    // Without this the camera is a button that does nothing on
    // Android: the plugin is what writes `CAMERA` into the manifest,
    // and `launchCameraAsync` fails at the permission check before it
    // ever opens. iOS happened to work because the usage strings
    // above are set by hand, which is why only half the platforms
    // were broken.
    [
      'expo-image-picker',
      {
        photosPermission:
          'Choose existing photos of your clothes to add them to your wardrobe.',
        cameraPermission:
          'Take photos of your clothes to add them to your wardrobe.',
      },
    ],
    // Required for push to work at all in a build: it is what wires
    // the native notification entitlements and the Android channel.
    // Local scheduled reminders worked without it, which is why its
    // absence went unnoticed until the server gained a push pipeline.
    'expo-notifications',
    [
      'expo-audio',
      {
        // `$(PRODUCT_NAME)` is substituted at build time from the app's
        // own name, so this does not hardcode a product name — the
        // branding rule holds.
        microphonePermission:
          'Allow $(PRODUCT_NAME) to record what you say, so you can talk to the stylist instead of typing.',
      },
    ],
    // Playing a video somebody sent in a thread. Bundled in Expo Go,
    // so it needs no development build to work.
    'expo-video',
    [
      'expo-media-library',
      {
        // Write only. Saving a picture of yourself is the whole use, and
        // a feature that saves one has no business reading the rest of
        // somebody's camera roll.
        //
        // `$(PRODUCT_NAME)` is substituted at build time from the app's
        // own name, so this does not hardcode a product name.
        savePhotosPermission:
          'Allow $(PRODUCT_NAME) to save pictures of your avatar to your photos.',
        photosPermission:
          'Allow $(PRODUCT_NAME) to save pictures of your avatar to your photos.',
        isAccessMediaLocationEnabled: false,
      },
    ],
    [
      'expo-splash-screen',
      {
        // Warm paper ground, matching Colors.light.background.
        backgroundColor: '#FAF7F2',
        image: './assets/images/splash-icon.png',
        imageWidth: 76,
      },
    ],
  ],

  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },

  extra: {
    // What `getExpoPushTokenAsync` needs to mint a push token for
    // this installation. Without it the app cannot be reached by the
    // server's notification pipeline at all - see
    // `features/notifications/permission.pushToken`.
    eas: { projectId: '007fab39-2880-4a8e-9e64-642908202e5a' },
    brand: {
      tagline: brand.tagline,
      isWorkingName: brand.isWorkingName,
      support: brand.support,
      urls: brand.urls,
    },
  },
};

export default config;
