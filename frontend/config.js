// Isi nilai ini. Anon/publishable key SELAMAT untuk frontend (RLS melindungi data).
window.MAL_CONFIG = {
  // false = buka terus tanpa log masuk (sesiapa ada URL boleh lihat & sunting tag/status)
  REQUIRE_LOGIN: false,

  SUPABASE_URL: "https://xjykwwwkdbkzouplwodb.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_Xxkcq8qYuTw5DlAoOrRh3g_kUG0zeSq",

  // Alamat DSM untuk butang "Salin link" (buka fail dalam File Station).
  // QuickConnect: "https://YOURID.quickconnect.to"  | LAN/VPN: "https://192.168.1.10:5001"
  NAS_WEB_URL: "https://YOURID.quickconnect.to",

  // Laluan rangkaian (SMB) untuk salin ke Finder/Explorer. Kosongkan jika tak guna.
  // Windows: "\\\\NAS-NAME"  | macOS: "smb://NAS-NAME"
  SMB_PREFIX: "\\\\NAS-NAME",

  PAGE_SIZE: 60,
};
