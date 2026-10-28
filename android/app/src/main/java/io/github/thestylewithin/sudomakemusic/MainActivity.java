package io.github.thestylewithin.sudomakemusic;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.text.InputType;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Thin client: shows the sudo-make-music web UI served by the desktop app on your own network.
 * The model runs on the PC (a phone cannot run it); nothing leaves your LAN.
 * On the PC: sudo-make-music --host 0.0.0.0   (prints the URL with a token).
 */
public class MainActivity extends Activity {
    private WebView web;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        SharedPreferences sp = getSharedPreferences("smm", MODE_PRIVATE);
        String url = sp.getString("url", "");
        if (url.isEmpty()) showSetup(sp); else showWeb(url);
    }

    private void showSetup(SharedPreferences sp) {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setPadding(48, 96, 48, 48);
        TextView t = new TextView(this);
        t.setText("Enter the address printed by the desktop app,\ne.g. http://192.168.1.20:7860/?token=abc123");
        t.setTextSize(16);
        EditText e = new EditText(this);
        e.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        e.setHint("http://<pc-ip>:7860/?token=...");
        Button go = new Button(this);
        go.setText("Connect");
        go.setOnClickListener(v -> {
            String u = e.getText().toString().trim();
            if (!u.startsWith("http")) u = "http://" + u;
            sp.edit().putString("url", u).apply();
            showWeb(u);
        });
        l.addView(t);
        l.addView(e);
        l.addView(go);
        setContentView(l);
    }

    private void showWeb(String url) {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        CookieManager.getInstance().setAcceptCookie(true);
        web.setWebViewClient(new WebViewClient());
        web.setDownloadListener((u, ua, cd, mime, len) -> {
            DownloadManager.Request r = new DownloadManager.Request(Uri.parse(u));
            r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            r.setDestinationInExternalPublicDir(Environment.DIRECTORY_MUSIC, URLUtil.guessFileName(u, cd, mime));
            String cookie = CookieManager.getInstance().getCookie(u);
            if (cookie != null) r.addRequestHeader("Cookie", cookie);
            ((DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(r);
        });
        web.loadUrl(url);
        setContentView(web);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        // Leaving the UI forgets the server so a different PC can be entered next launch.
        getSharedPreferences("smm", MODE_PRIVATE).edit().remove("url").apply();
        super.onBackPressed();
    }
}
