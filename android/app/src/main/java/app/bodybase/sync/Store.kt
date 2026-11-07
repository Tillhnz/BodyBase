package app.bodybase.sync

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import java.time.Instant
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Der Schlüssel wird mit einem Geräteschlüssel aus dem Android Keystore verschlüsselt abgelegt. */
object Secret {
    private const val ALIAS = "bodybase-sync"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        )
        return gen.generateKey()
    }

    fun encrypt(text: String): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        return Base64.encodeToString(c.iv + c.doFinal(text.toByteArray()), Base64.NO_WRAP)
    }

    fun decrypt(data: String): String? = runCatching {
        val b = Base64.decode(data, Base64.NO_WRAP)
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, b, 0, 12))
        String(c.doFinal(b, 12, b.size - 12))
    }.getOrNull()
}

class Prefs(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("bodybase", Context.MODE_PRIVATE)

    var url: String
        get() = sp.getString("url", "") ?: ""
        set(v) = sp.edit().putString("url", v.trim()).apply()

    var key: String
        get() = sp.getString("key", null)?.let { Secret.decrypt(it) } ?: ""
        set(v) = sp.edit().putString("key", Secret.encrypt(v.trim())).apply()

    /** Minuten zwischen automatischen Abgleichen, 0 = aus. */
    var interval: Int
        get() = sp.getInt("interval", 30)
        set(v) = sp.edit().putInt("interval", v).apply()

    fun cursor(kind: String): Instant? = sp.getLong("c_$kind", 0L).takeIf { it > 0 }?.let { Instant.ofEpochMilli(it) }

    fun setCursor(kind: String, t: Instant) {
        sp.edit().putLong("c_$kind", t.toEpochMilli()).commit()
    }

    fun clearCursor(kind: String) {
        sp.edit().remove("c_$kind").commit()
    }

    var aggregatedResent: Boolean
        get() = sp.getBoolean("aggregated_resent", false)
        set(v) = sp.edit().putBoolean("aggregated_resent", v).apply()

    /** start = null: wieder wie beim ersten Mal (30 Tage); sonst ab diesem Zeitpunkt alles neu senden. */
    fun resetCursors(start: Instant?) {
        val e = sp.edit()
        Kinds.ALL.forEach { if (start == null) e.remove("c_${it.key}") else e.putLong("c_${it.key}", start.toEpochMilli()) }
        e.commit()
    }

    var lastRun: Long
        get() = sp.getLong("last_run", 0L)
        set(v) = sp.edit().putLong("last_run", v).apply()

    var lastAttempt: Long
        get() = sp.getLong("last_attempt", 0L)
        set(v) = sp.edit().putLong("last_attempt", v).apply()

    var lastError: String?
        get() = sp.getString("last_error", null)
        set(v) = sp.edit().putString("last_error", v).apply()

    var lastCounts: Map<String, Int>
        get() {
            val j = JSONObject(sp.getString("last_counts", null) ?: "{}")
            return j.keys().asSequence().associateWith { j.optInt(it) }
        }
        set(v) = sp.edit().putString("last_counts", JSONObject(v as Map<*, *>).toString()).apply()

    var total: Long
        get() = sp.getLong("total", 0L)
        set(v) = sp.edit().putLong("total", v).apply()
}
