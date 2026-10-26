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
    brand: {
      tagline: brand.tagline,
      isWorkingName: brand.isWorkingName,
      support: brand.support,
      urls: brand.urls,
    },
  },
};

export default config;
