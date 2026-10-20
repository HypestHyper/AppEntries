from app_entries import packages


def fake(outputs, installed):
    def run(argv):
        return outputs.get(argv[0])
    return run, (lambda name: "/usr/bin/" + name if name in installed else None)


def test_pacman():
    run, which = fake({"pacman": "systemsettings\n"}, {"pacman"})
    o = packages.owner_of("/usr/share/applications/kcm_style.desktop", run=run, which=which)
    assert (o.package, o.manager, o.command) == ("systemsettings", "pacman", "sudo pacman -Rns systemsettings")


def test_dpkg_strips_architecture():
    run, which = fake({"dpkg-query": "kde-config-gtk-style:amd64: /usr/share/applications/kcm_style.desktop\n"},
                      {"dpkg-query"})
    o = packages.owner_of("/usr/share/applications/kcm_style.desktop", run=run, which=which)
    assert (o.package, o.command) == ("kde-config-gtk-style", "sudo apt remove kde-config-gtk-style")


def test_rpm_picks_the_frontend():
    run, which = fake({"rpm": "plasma-desktop\n"}, {"rpm", "dnf"})
    assert packages.owner_of("/x.desktop", run=run, which=which).command == "sudo dnf remove plasma-desktop"
    run, which = fake({"rpm": "plasma-desktop\n"}, {"rpm", "zypper"})
    assert packages.owner_of("/x.desktop", run=run, which=which).command == "sudo zypper remove plasma-desktop"


def test_flatpak_and_snap_need_no_lookup():
    run, which = fake({}, set())
    o = packages.owner_of("/var/lib/flatpak/exports/share/applications/org.x.App.desktop", "flatpak", run, which)
    assert o.command == "flatpak uninstall org.x.App"
    o = packages.owner_of("/var/lib/snapd/desktop/applications/vlc_vlc.desktop", "snap", run, which)
    assert o.command == "sudo snap remove vlc"


def test_unknown_owner():
    run, which = fake({"pacman": None}, {"pacman"})
    assert packages.owner_of("/usr/share/applications/hand-made.desktop", run=run, which=which) is None
    run, which = fake({}, set())
    assert packages.owner_of("/x.desktop", run=run, which=which) is None
