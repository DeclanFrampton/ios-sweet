using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Uninstall {
    [STAThread] static void Main() {
        string app=Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory).TrimEnd('\\');
        using(var key=Registry.CurrentUser.OpenSubKey(@"Software\IOSSweetStudio")) {
            if(key==null || !String.Equals(app,key.GetValue("InstallDirectory") as string,StringComparison.OrdinalIgnoreCase) || !File.Exists(Path.Combine(app,".studio-install"))) {
                MessageBox.Show("This is not the registered Studio installation. Nothing was removed.");return;
            }
        }
        Mutex running;
        if(Mutex.TryOpenExisting(@"Local\IOSSweetStudioDesktop",out running)){running.Dispose();MessageBox.Show("Close iOS Sweet Studio and stop its iPhone before uninstalling.");return;}
        if(Process.GetProcessesByName("qemu-system-aarch64").Length>0){MessageBox.Show("Stop the iPhone before uninstalling. No running process was changed.");return;}
        if(MessageBox.Show("Remove iOS Sweet Studio? Your private iPhone data, installed apps and logs will be kept.","Uninstall iOS Sweet Studio",MessageBoxButtons.YesNo)!=DialogResult.Yes)return;
        foreach(var folder in new[]{Environment.SpecialFolder.DesktopDirectory,Environment.SpecialFolder.Programs,Environment.SpecialFolder.SendTo}) {
            string link=Path.Combine(Environment.GetFolderPath(folder),"iOS Sweet Studio.lnk");if(File.Exists(link))File.Delete(link);
        }
        Registry.CurrentUser.DeleteSubKeyTree(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\IOSSweetStudio",false);
        Registry.CurrentUser.DeleteSubKeyTree(@"Software\Classes\Applications\iOS Sweet Studio.exe",false);
        Registry.CurrentUser.DeleteSubKeyTree(@"Software\Classes\.ipa\OpenWithList\iOS Sweet Studio.exe",false);
        // A single PowerShell process removes only the verified application root
        // after this executable exits; no cross-shell deletion or user-data path.
        string script="Start-Sleep -Seconds 2;$p='"+app.Replace("'","''")+"';if(Test-Path -LiteralPath (Join-Path $p '.studio-install')){Remove-Item -LiteralPath $p -Recurse -Force}";
        Process.Start(new ProcessStartInfo("powershell.exe","-NoProfile -NonInteractive -EncodedCommand "+Convert.ToBase64String(System.Text.Encoding.Unicode.GetBytes(script))){UseShellExecute=false,CreateNoWindow=true});
    }
}
