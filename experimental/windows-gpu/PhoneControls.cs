using System;
using System.Diagnostics;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;

// A user-operated companion for the native SDL viewer. No QMP input injection.
class PhoneControls : Form
{
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int L,T,R,B; }
    [StructLayout(LayoutKind.Sequential)] struct POINT { public int X,Y; }
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT { public int dx,dy; public uint data,flags,time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Sequential)] struct INPUT { public uint type; public MOUSEINPUT mouse; }
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr h,out RECT r);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr h,ref POINT p);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int n);
    [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint n,INPUT[] v,int size);
    readonly Button home = new Button { Text="Home / SpringBoard", Dock=DockStyle.Top, Height=48, AccessibleName="Home / SpringBoard" };
    readonly Button unlock = new Button { Text="Swipe up / unlock", Dock=DockStyle.Top, Height=40 };
    readonly Label status = new Label { Text="Home uses the viewer's native iOS shortcut.", Dock=DockStyle.Fill, Padding=new Padding(10) };
    bool busy;

    PhoneControls()
    {
        Text="iPhone controls"; ClientSize=new Size(260,155); FormBorderStyle=FormBorderStyle.FixedSingle; MaximizeBox=false;
        TopMost=true; StartPosition=FormStartPosition.Manual;
        Location=new Point(Screen.PrimaryScreen.WorkingArea.Right-280,Screen.PrimaryScreen.WorkingArea.Top+90);
        Controls.Add(status); Controls.Add(unlock); Controls.Add(home);
        home.Click += async (s,e) => await Home(false);
        unlock.Click += async (s,e) => await Home(true);
        FormClosing += (s,e) => { if(busy) {e.Cancel=true;status.Text="Wait for the gesture to release, then close.";} };
    }

    static IntPtr FindViewer()
    {
        IntPtr found=IntPtr.Zero;
        foreach(var p in Process.GetProcessesByName("qemu-system-aarch64"))
        using(p) {
            if(p.MainWindowHandle==IntPtr.Zero || !(p.MainWindowTitle.StartsWith("Reims vGPU") || p.MainWindowTitle.StartsWith("Native Windows iPhone GPU experiment"))) continue;
            if(found!=IntPtr.Zero) throw new InvalidOperationException("Multiple phone viewers: close the extra instance first.");
            found=p.MainWindowHandle;
        }
        if(found==IntPtr.Zero || IsIconic(found)) throw new InvalidOperationException("Open the running Reims phone window first.");
        return found;
    }

    // The SDL renderer aspect-fits the 860x1864 guest inside the client area.
    internal static Rectangle ImageArea(int w,int h)
    {
        double scale=Math.Min(w/860.0,h/1864.0);
        int iw=(int)Math.Round(860*scale), ih=(int)Math.Round(1864*scale);
        return new Rectangle((w-iw)/2,(h-ih)/2,iw,ih);
    }
    static void Mouse(int x,int y,uint flags)
    {
        int vx=GetSystemMetrics(76),vy=GetSystemMetrics(77),vw=GetSystemMetrics(78),vh=GetSystemMetrics(79);
        var input=new INPUT { type=0,mouse=new MOUSEINPUT { dx=(int)Math.Round((x-vx)*65535.0/Math.Max(1,vw-1)),dy=(int)Math.Round((y-vy)*65535.0/Math.Max(1,vh-1)),flags=flags|0x8000|0x4000|1 } };
        if(SendInput(1,new[]{input},Marshal.SizeOf(typeof(INPUT)))!=1) throw new InvalidOperationException("Windows refused mouse input; use the same privilege level as the viewer.");
    }
    async Task Home(bool swipe)
    {
        if(busy)return; busy=true;home.Enabled=false;unlock.Enabled=false;
        bool down=false; int x=0,y=0;
        try {
            var viewer=FindViewer(); RECT r;
            if(!GetClientRect(viewer,out r))throw new InvalidOperationException("Cannot read viewer size.");
            var image=ImageArea(r.R-r.L,r.B-r.T);
            if(image.Height<200)throw new InvalidOperationException("Enlarge the viewer first.");
            POINT origin=new POINT();ClientToScreen(viewer,ref origin);
            x=origin.X+image.Left+image.Width/2;
            int start=origin.Y+image.Top+(int)(image.Height*0.96);
            int end=origin.Y+image.Top+(int)(image.Height*0.42);
            SetForegroundWindow(viewer); await Task.Delay(100);
            if(GetForegroundWindow()!=viewer)throw new InvalidOperationException("Click the phone once and retry Home.");
            if(!swipe) {
                y=origin.Y+image.Top+image.Height/2;
                Mouse(x,y,0x20);down=true;
                await Task.Delay(150);
                Mouse(x,y,0x40);down=false;
                status.Text="Home shortcut sent. Allow the phone to respond.";return;
            }
            status.Text="Swiping up…"; y=start; Mouse(x,y,2);down=true;
            await Task.Delay(350); // give the emulated HID endpoint time to observe the press
            for(int i=1;i<=24;i++) {
                await Task.Delay(40);
                if(GetForegroundWindow()!=viewer)throw new InvalidOperationException("Gesture cancelled: focus changed.");
                y=start+(end-start)*i/24;Mouse(x,y,0);
            }
            Mouse(x,y,4);down=false;
            status.Text="Home gesture sent. Allow the phone to respond.";
        } catch(Exception ex) {status.Text=ex.Message;}
        finally {
            if(down) {try {Mouse(x,y,swipe?4u:0x40u);} catch {} }
            home.Enabled=true;unlock.Enabled=true;busy=false;
        }
    }
    [STAThread] static int Main(string[] args)
    {
        if(args.Length>0 && args[0]=="--self-test") {
            var a=ImageArea(830,630);var b=ImageArea(430,932);
            return a.Width==291 && a.Height==630 && a.Left==269 && b.Width==430 && b.Left==0 && Marshal.SizeOf(typeof(INPUT))==(IntPtr.Size==8?40:28)?0:1;
        }
        SetProcessDPIAware();Application.EnableVisualStyles();Application.Run(new PhoneControls());return 0;
    }
}
