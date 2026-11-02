package app.bodybase.sync

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Farben wie in der BodyBase-Weboberfläche
object C {
    val Ink = Color(0xFF0D1119)
    val Panel = Color(0xFF161D2A)
    val Panel2 = Color(0xFF1C2534)
    val Line = Color(0xFF263246)
    val Line2 = Color(0xFF33435C)
    val Chalk = Color(0xFFECF0F5)
    val Mute = Color(0xFF8B97AB)
    val Iris = Color(0xFF9AA8FF)
    val IrisInk = Color(0xFF0B1030)
    val Good = Color(0xFF5EE2A0)
    val Signal = Color(0xFFFF5D6C)
    val Warn = Color(0xFFF5B84B)
    val Activity = Color(0xFFF5A524)
    val Heart = Color(0xFFFF6B81)
    val Sleep = Color(0xFF8B7CFF)
}

@Composable
fun BodyBaseTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = C.Iris, onPrimary = C.IrisInk,
            secondary = C.Iris, onSecondary = C.IrisInk,
            background = C.Ink, onBackground = C.Chalk,
            surface = C.Panel, onSurface = C.Chalk,
            surfaceVariant = C.Panel2, onSurfaceVariant = C.Mute,
            surfaceContainerHigh = C.Panel2, surfaceContainer = C.Panel,
            outline = C.Line2, outlineVariant = C.Line,
            error = C.Signal,
        ),
        content = content,
    )
}

/** Die drei Ringe aus dem BodyBase-Logo. */
@Composable
fun Logo(size: Dp) {
    Canvas(Modifier.size(size)) {
        val u = this.size.minDimension / 64f
        listOf(24f to C.Activity, 16f to C.Heart, 8f to C.Sleep).forEach { (r, color) ->
            val tl = Offset(center.x - r * u, center.y - r * u)
            val sz = Size(2 * r * u, 2 * r * u)
            drawArc(C.Line, 0f, 360f, false, tl, sz, style = Stroke(5 * u))
            drawArc(color, -90f, 240f, false, tl, sz, style = Stroke(5 * u, cap = StrokeCap.Round))
        }
        drawCircle(C.Iris, 3.2f * u)
    }
}

@Composable
fun Panel(title: String, sub: String? = null, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        color = C.Panel,
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, C.Line),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Column {
                Text(title, fontSize = 19.sp, fontWeight = FontWeight.SemiBold, color = C.Chalk)
                if (sub != null) Text(sub, fontSize = 13.sp, color = C.Mute)
            }
            content()
        }
    }
}

@Composable
fun Dot(color: Color, size: Dp = 8.dp) {
    Box(Modifier.size(size).background(color, CircleShape))
}

/** Kleine Statuszeile mit farbigem Punkt. */
@Composable
fun StatusLine(ok: Boolean?, text: String) {
    val color = when (ok) {
        true -> C.Good
        false -> C.Signal
        null -> C.Warn
    }
    Row(
        Modifier
            .fillMaxWidth()
            .background(color.copy(alpha = 0.09f), RoundedCornerShape(12.dp))
            .border(1.dp, color.copy(alpha = 0.3f), RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(Modifier.padding(top = 6.dp)) { Dot(color) }
        Spacer(Modifier.width(10.dp))
        Text(text, fontSize = 14.sp, color = C.Chalk, lineHeight = 19.sp)
    }
}

@Composable
fun Chip(label: String, color: Color, on: Boolean) {
    Row(
        Modifier
            .background(if (on) color.copy(alpha = 0.12f) else C.Panel2, RoundedCornerShape(50))
            .border(1.dp, if (on) color.copy(alpha = 0.45f) else C.Line, RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Dot(if (on) color else C.Line2, 7.dp)
        Spacer(Modifier.width(6.dp))
        Text(label, fontSize = 13.sp, color = if (on) C.Chalk else C.Mute)
    }
}

@Composable
fun PrimaryButton(text: String, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(containerColor = C.Iris, contentColor = C.IrisInk),
        modifier = modifier,
    ) { Text(text, fontWeight = FontWeight.SemiBold) }
}

@Composable
fun GhostButton(text: String, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, C.Line2),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = C.Chalk),
        modifier = modifier,
    ) { Text(text) }
}
