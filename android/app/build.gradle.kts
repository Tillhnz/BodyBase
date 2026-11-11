plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Versionsnummer kommt aus dem GitHub-Build (-PversionCode=…), damit jede neue APK als Update installiert werden kann.
val vCode = (project.findProperty("versionCode") as String?)?.toIntOrNull() ?: 1

android {
    namespace = "app.bodybase.sync"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.bodybase.sync"
        minSdk = 28
        targetSdk = 35
        versionCode = vCode
        versionName = "1.0.$vCode"
    }

    signingConfigs {
        create("release") {
            // Eigener Schlüssel per Umgebungsvariablen möglich, sonst der mitgelieferte (gleich bleibend, damit Updates klappen).
            storeFile = file(System.getenv("BB_KEYSTORE") ?: "../bodybase-sync.jks")
            storePassword = System.getenv("BB_KEYSTORE_PASSWORD") ?: "bodybase-sync"
            keyAlias = System.getenv("BB_KEY_ALIAS") ?: "bodybase-sync"
            keyPassword = System.getenv("BB_KEY_PASSWORD") ?: "bodybase-sync"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        freeCompilerArgs.addAll(
            "-opt-in=androidx.health.connect.client.feature.ExperimentalFeatureAvailabilityApi",
            "-opt-in=androidx.compose.material3.ExperimentalMaterial3Api",
            "-opt-in=androidx.compose.foundation.layout.ExperimentalLayoutApi",
        )
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.12.0")
    implementation("androidx.health.connect:connect-client:1.1.0")
}
