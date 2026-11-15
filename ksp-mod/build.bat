@echo off
set "KSP_DIR=D:\SteamLibrary\steamapps\common\Kerbal Space Program"
set "MANAGED=%KSP_DIR%\KSP_x64_Data\Managed"
set "MOD_DIR=%KSP_DIR%\GameData\OrionMedKSP\Plugins"

if not exist "%MOD_DIR%" mkdir "%MOD_DIR%"

echo [1/2] Compiling OrionMedKSP.dll...
"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /codepage:65001 /target:library /optimize+ /out:"%MOD_DIR%\OrionMedKSP.dll" /r:"%MANAGED%\Assembly-CSharp.dll" /r:"%MANAGED%\UnityEngine.dll" /r:"%MANAGED%\UnityEngine.CoreModule.dll" /r:"%MANAGED%\UnityEngine.InputLegacyModule.dll" /r:"%MANAGED%\UnityEngine.IMGUIModule.dll" /r:"%MANAGED%\UnityEngine.JSONSerializeModule.dll" /r:"%MANAGED%\UnityEngine.UnityWebRequestModule.dll" /r:"%MANAGED%\UnityEngine.AnimationModule.dll" /r:"%MANAGED%\UnityEngine.UI.dll" "%~dp0OrionMedKSP.cs"

if errorlevel 1 goto :err

echo [2/2] SUCCESS! Installed to: "%MOD_DIR%\OrionMedKSP.dll"
goto :eof

:err
echo [ERROR] Compilation failed.
exit /b 1
