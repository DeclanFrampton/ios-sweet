// Per-user, self-contained installer. Never installs Apple firmware or touches
// the user's device data. Build with .NET Framework csc and an embedded ZIP.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Setup {
    internal const string Product = "iOS Sweet Studio";
    internal const string Version = "0.2.0-preview";
    internal static string Target = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", Product);
    internal static string Data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Product);
    internal static bool Quiet, NoLaunch, NoShortcuts;

    [STAThread] public static int Main(string[] args) {
        Application.EnableVisualStyles();
        foreach(string arg in args) {
            if(arg == "/quiet") Quiet = true;
            else if(arg == "/no-launch") NoLaunch = true;
            else if(arg == "/no-shortcuts") NoShortcuts = true;
            else if(arg.StartsWith("/dir=")) Target = Path.GetFullPath(arg.Substring(5));
            else if(arg.StartsWith("/data=")) Data = Path.GetFullPath(arg.Substring(6));
            else { MessageBox.Show("Unknown setup argument.", Product); return 2; }
        }
        if(!Environment.Is64BitOperatingSystem || String.Equals(Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE"), "ARM64", StringComparison.OrdinalIgnoreCase)) {
            MessageBox.Show("This preview requires Windows 10/11 on an Intel or AMD 64-bit computer.", Product); return 2;
        }
        if(Quiet) {
            try { Install(delegate(string s) { Console.WriteLine(s); }); return 0; }
            catch(Exception e) { File.WriteAllText(Path.Combine(Path.GetTempPath(), "iossweet-setup-error.log"), e.ToString()); return 1; }
        }
        using(var form = new SetupForm()) Application.Run(form);
        return 0;
    }

    static void AssertOwnedDirectory(string path, bool existing) {
        string full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
        if(full.Length < 12 || String.Equals(full, Path.GetPathRoot(full).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Choose a dedicated application folder, not a drive root.");
        for(DirectoryInfo p = new DirectoryInfo(full); p != null; p = p.Parent) {
            if(p.Exists && (p.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException("Setup does not install through junctions or symbolic links.");
        }
        if(existing && Directory.Exists(full) && Directory.GetFileSystemEntries(full).Length > 0 && !File.Exists(Path.Combine(full,".studio-install")))
            throw new InvalidOperationException("The destination contains other files. Choose an empty folder or an existing Studio installation.");
    }

    static string Digest(Stream stream) {
        using(var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    static bool WebViewInstalled() {
        const string id = @"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
        foreach(var hive in new[]{RegistryHive.CurrentUser, RegistryHive.LocalMachine})
            foreach(var view in new[]{RegistryView.Registry32, RegistryView.Registry64})
                using(var root = RegistryKey.OpenBaseKey(hive, view))
                using(var key = root.OpenSubKey(id)) {
                    var version = key == null ? null : key.GetValue("pv") as string;
                    if(!String.IsNullOrEmpty(version) && version != "0.0.0.0") return true;
                }
        return false;
    }

    static void EnsureWebView(Action<string> progress) {
        if(WebViewInstalled()) return;
        progress("Installing the Microsoft WebView2 display component...");
        string temp = Path.Combine(Path.GetTempPath(), "iossweet-webview-" + Guid.NewGuid().ToString("N") + ".exe");
        try {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            using(var client = new WebClient()) client.DownloadFile("https://go.microsoft.com/fwlink/p/?LinkId=2124703", temp);
            string script = "$s=Get-AuthenticodeSignature -LiteralPath '" + temp.Replace("'", "''") + "';if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation'){exit 9}";
            var verify = Process.Start(new ProcessStartInfo("powershell.exe", "-NoProfile -NonInteractive -EncodedCommand " + Convert.ToBase64String(System.Text.Encoding.Unicode.GetBytes(script))) { UseShellExecute=false,CreateNoWindow=true });
            verify.WaitForExit(); if(verify.ExitCode != 0) throw new InvalidOperationException("The WebView2 download did not have a valid Microsoft signature.");
            var install = Process.Start(new ProcessStartInfo(temp, "/silent /install") { UseShellExecute=false,CreateNoWindow=true });
            if(!install.WaitForExit(600000)) throw new TimeoutException("WebView2 installation has not completed.");
            if(!WebViewInstalled()) throw new InvalidOperationException("Microsoft WebView2 could not be installed. Install the Evergreen Runtime from Microsoft, then retry.");
        } finally { if(File.Exists(temp)) File.Delete(temp); }
    }

    internal static void Install(Action<string> progress) {
        Mutex running;
        if(Mutex.TryOpenExisting(@"Local\IOSSweetStudioDesktop", out running)) {
            running.Dispose(); throw new InvalidOperationException("Close iOS Sweet Studio before installing an update.");
        }
        Target=Path.GetFullPath(Target);Data=Path.GetFullPath(Data);
        AssertOwnedDirectory(Target,true);
        if(Data.StartsWith(Target.TrimEnd('\\') + "\\",StringComparison.OrdinalIgnoreCase) || String.Equals(Data,Target,StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Device data must be outside the application folder so upgrades cannot overwrite it.");
        AssertOwnedDirectory(Data,false);
        EnsureWebView(progress);
        string parent=Path.GetDirectoryName(Target);Directory.CreateDirectory(parent);
        string stage=Path.Combine(parent,".iossweet-install-"+Guid.NewGuid().ToString("N"));
        string backup=Target+".previous-"+Guid.NewGuid().ToString("N");
        Directory.CreateDirectory(stage);
        bool movedOld=false,committed=false;
        try {
            progress("Verifying the application package...");
            var assembly=Assembly.GetExecutingAssembly();
            string expected;
            using(var reader=new StreamReader(assembly.GetManifestResourceStream("payload.sha256"))) expected=reader.ReadToEnd().Trim();
            using(var payload=assembly.GetManifestResourceStream("payload.zip")) {
                if(payload==null || Digest(payload)!=expected)throw new InvalidDataException("Installer payload checksum mismatch.");
                payload.Position=0;
                using(var zip=new ZipArchive(payload,ZipArchiveMode.Read)) {
                    int index=0;
                    foreach(var entry in zip.Entries) {
                        string path=Path.GetFullPath(Path.Combine(stage,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                        if(!path.StartsWith(stage+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase) || entry.FullName.Contains(":"))
                            throw new InvalidDataException("Unsafe package entry.");
                        if(entry.Name.Length==0){Directory.CreateDirectory(path);continue;}
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using(var from=entry.Open()) using(var to=new FileStream(path,FileMode.CreateNew))from.CopyTo(to);
                        if((++index%25)==0)progress("Installing application files: "+index+" / "+zip.Entries.Count);
                    }
                }
            }
            if(!File.Exists(Path.Combine(stage,Product+".exe")))throw new InvalidDataException("Application executable is missing.");
            File.WriteAllText(Path.Combine(stage,".studio-install"),Version);
            if(Directory.Exists(Target)){Directory.Move(Target,backup);movedOld=true;}
            try { Directory.Move(stage,Target);committed=true; }
            catch {if(movedOld)Directory.Move(backup,Target);throw;}
            Directory.CreateDirectory(Data);
            using(var key=Registry.CurrentUser.CreateSubKey(@"Software\IOSSweetStudio")) {
                key.SetValue("InstallDirectory",Target);key.SetValue("DataDirectory",Data);key.SetValue("Version",Version);
            }
            using(var key=Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\IOSSweetStudio")) {
                key.SetValue("DisplayName",Product);key.SetValue("DisplayVersion",Version);key.SetValue("Publisher","iOS Sweet community project");
                key.SetValue("InstallLocation",Target);key.SetValue("DisplayIcon",Path.Combine(Target,Product+".exe"));
                key.SetValue("UninstallString","\""+Path.Combine(Target,"Uninstall.exe")+"\"");
                key.SetValue("NoModify",1,RegistryValueKind.DWord);key.SetValue("NoRepair",1,RegistryValueKind.DWord);
            }
            if(!NoShortcuts) {
                MakeShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),Product+".lnk"),"");
                MakeShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),Product+".lnk"),"");
                MakeShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.SendTo),Product+".lnk"),"--ipa");
                // Offer Open with, without replacing the user's default IPA application.
                using(var key=Registry.CurrentUser.CreateSubKey(@"Software\Classes\Applications\iOS Sweet Studio.exe\shell\open\command"))
                    key.SetValue("","\""+Path.Combine(Target,Product+".exe")+"\" --ipa \"%1\"");
                using(var key=Registry.CurrentUser.CreateSubKey(@"Software\Classes\.ipa\OpenWithList\iOS Sweet Studio.exe"))key.SetValue("", "");
            }
            progress("Installed. Your existing iPhone data has been preserved.");
            if(movedOld){AssertOwnedDirectory(backup,true);Directory.Delete(backup,true);}
            if(!NoLaunch)Process.Start(new ProcessStartInfo(Path.Combine(Target,Product+".exe")){WorkingDirectory=Target,UseShellExecute=true});
        } finally {
            if(!committed && Directory.Exists(stage) && stage.StartsWith(parent+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))Directory.Delete(stage,true);
        }
    }

    static void MakeShortcut(string path,string arguments) {
        dynamic shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        dynamic shortcut=shell.CreateShortcut(path);
        shortcut.TargetPath=Path.Combine(Target,Product+".exe");shortcut.WorkingDirectory=Target;shortcut.Arguments=arguments;
        shortcut.Description="Install and run iOS development apps locally";shortcut.Save();
    }

    sealed class SetupForm : Form {
        readonly TextBox destination=new TextBox(),data=new TextBox();
        readonly Label status=new Label();readonly Button install=new Button();readonly ProgressBar bar=new ProgressBar();
        bool working;
        public SetupForm() {
            Text=Product+" Setup";ClientSize=new Size(600,390);StartPosition=FormStartPosition.CenterScreen;FormBorderStyle=FormBorderStyle.FixedDialog;
            MaximizeBox=false;BackColor=Color.FromArgb(14,21,39);ForeColor=Color.White;Font=new Font("Segoe UI",10);
            var title=new Label{Text=Product,Font=new Font("Segoe UI",25,FontStyle.Bold),AutoSize=true,Location=new Point(28,25)};
            var detail=new Label{Text="Your local iPhone. One app for IPA installation and testing.",AutoSize=true,Location=new Point(31,80)};
            var dl=new Label{Text="Application folder",AutoSize=true,Location=new Point(31,122)};
            destination.SetBounds(31,146,535,28);destination.Text=Target;
            var dataLabel=new Label{Text="Private iPhone data folder (choose a drive with 35 GB free)",AutoSize=true,Location=new Point(31,186)};
            data.SetBounds(31,210,535,28);data.Text=Data;
            status.SetBounds(31,252,535,44);status.Text="Includes native QEMU and signing tools. Apple firmware is prepared privately on first launch.";
            bar.SetBounds(31,303,535,5);bar.Visible=false;
            install.SetBounds(365,330,201,38);install.Text="Install & open Studio";install.BackColor=Color.FromArgb(167,243,208);install.ForeColor=Color.FromArgb(9,45,36);install.FlatStyle=FlatStyle.Flat;
            install.Click+=async delegate {
                Target=destination.Text;Data=data.Text;working=true;install.Enabled=false;destination.Enabled=false;data.Enabled=false;bar.Visible=true;bar.Style=ProgressBarStyle.Marquee;
                try { await Task.Run(()=>Install(s=>BeginInvoke((Action)(()=>status.Text=s))));working=false;Close(); }
                catch(Exception ex){MessageBox.Show(ex.Message,Product,MessageBoxButtons.OK,MessageBoxIcon.Error);working=false;install.Enabled=true;destination.Enabled=true;data.Enabled=true;bar.Visible=false;}
            };
            Controls.AddRange(new Control[]{title,detail,dl,destination,dataLabel,data,status,bar,install});
            FormClosing+=delegate(object sender,FormClosingEventArgs e){if(working)e.Cancel=true;};
        }
    }
}
