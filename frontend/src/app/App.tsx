import { useState, useEffect } from 'react';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { Login } from './components/Login';
import { DashboardLayout } from './components/DashboardLayout';
import { MonitoringModule } from './components/MonitoringModule';
import { SpatialModule } from './components/SpatialModule';
import { AssessmentModule } from './components/AssessmentModule';
import { SettingsModule } from './components/SettingsModule';

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [username, setUsername] = useState('');
  const [role, setRole] = useState('');
  const [currentModule, setCurrentModule] = useState('home');
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    if (isDark) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
  }, [isDark]);

  const handleLogin = (user: string, userRole: string) => {
    setUsername(user);
    setRole(userRole);
    setIsLoggedIn(true);
  };

  const handleLogout = () => {
    setIsLoggedIn(false);
    setUsername('');
    setRole('');
    setCurrentModule('home');
  };

  const handleThemeToggle = () => {
    setIsDark(!isDark);
  };

  const theme = createTheme({
    palette: {
      mode: isDark ? 'dark' : 'light',
      primary: {
        main: isDark ? '#52b788' : '#2d6a4f',
      },
      secondary: {
        main: isDark ? '#42a5f5' : '#1e88e5',
      },
    },
  });

  const renderModule = () => {
    switch (currentModule) {
      case 'home':
        return <MonitoringModule />;
      case 'spatial':
        return <SpatialModule />;
      case 'assessment':
        return <AssessmentModule />;
      case 'settings':
        return <SettingsModule />;
      default:
        return <MonitoringModule />;
    }
  };

  if (!isLoggedIn) {
    return (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Login onLogin={handleLogin} />
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <DashboardLayout
        currentModule={currentModule}
        onModuleChange={setCurrentModule}
        onLogout={handleLogout}
        isDark={isDark}
        onThemeToggle={handleThemeToggle}
        username={username}
        role={role}
      >
        {renderModule()}
      </DashboardLayout>
    </ThemeProvider>
  );
}