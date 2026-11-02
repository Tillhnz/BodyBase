package app.bodybase.sync

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Wird von Health Connect angezeigt, wenn man wissen will, wofür die App die Daten nutzt. */
class PrivacyActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            BodyBaseTheme {
                Column(
                    Modifier
                        .fillMaxSize()
                        .background(C.Ink)
                        .safeDrawingPadding()
                        .verticalScroll(rememberScrollState())
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Logo(48.dp)
                    Text("Wofür BodyBase Sync deine Daten nutzt", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = C.Chalk)
                    listOf(
                        "BodyBase Sync liest die Gesundheitsdaten, die du freigibst, aus Health Connect und schickt sie an deinen eigenen BodyBase-Server – und nur dorthin.",
                        "Die Adresse des Servers legst du selbst fest. Es gibt keinen Dienst eines Dritten, keine Werbung und keine Analyse.",
                        "Die App liest nur, sie schreibt oder löscht nichts in Health Connect.",
                        "Den Zugriff kannst du jederzeit in Health Connect ändern oder ganz entziehen.",
                    ).forEach { Text(it, fontSize = 15.sp, color = C.Chalk, lineHeight = 21.sp) }
                }
            }
        }
    }
}
