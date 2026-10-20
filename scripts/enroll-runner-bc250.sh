#!/usr/bin/env bash
# Run once, locally as bc. Private SSH material never leaves either machine.
set -euo pipefail
[[ $(id -un) == bc ]] || { echo "Exécuter depuis le compte bc, sans sudo devant bash."; exit 1; }
expected_host='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIzJ5Hq0ndgAnTsu1aD9bNmxMSSWhsQK/Dj7d9cYVwpG'
runner_key='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH2Gadwk7R/atdgOHbOO/Hh9PlMcwjp9DxUpPmBgLmnC'
host_file=/etc/ssh/ssh_host_ed25519_key.pub
[[ -r "$host_file" ]] || { echo "Clé publique hôte SSH introuvable."; exit 1; }
actual_host=$(awk 'NR == 1 {print $1 " " $2}' "$host_file")
[[ "$actual_host" == "$expected_host" ]] || { echo "Identité BC-250 différente : aucune modification."; exit 1; }
[[ -x /usr/bin/systemctl && -x /usr/sbin/visudo ]] || { echo "systemctl ou visudo introuvable."; exit 1; }
systemctl cat doctrad2-bc250-runtime.service >/dev/null
# This only permits the three runtime lifecycle operations needed for sequential tests.
sudo -v
umask 077
access_dir="$HOME/.ssh"
[[ ! -L "$access_dir" ]] || { echo "Refus du répertoire SSH symbolique."; exit 1; }
mkdir -p "$access_dir"
chmod 700 "$access_dir"
[[ ! -L "$access_dir/authorized_keys" ]] || { echo "Refus du fichier authorized_keys symbolique."; exit 1; }
exec 9>"$access_dir/doctrad2-enrollment.lock"
flock -x 9
touch "$access_dir/authorized_keys"
chmod 600 "$access_dir/authorized_keys"
key_line='from="192.168.6.27",restrict '"$runner_key"' doctrad2-runner-to-bc250'
if ! grep -Fqx "$key_line" "$access_dir/authorized_keys"; then
  printf '\n%s\n' "$key_line" >> "$access_dir/authorized_keys"
fi
sudoers_tmp=$(mktemp)
trap 'rm -f "$sudoers_tmp"' EXIT
printf '%s\n' 'bc ALL=(root) NOPASSWD: /usr/bin/systemctl start doctrad2-bc250-runtime.service, /usr/bin/systemctl stop doctrad2-bc250-runtime.service, /usr/bin/systemctl restart doctrad2-bc250-runtime.service' > "$sudoers_tmp"
sudo /usr/sbin/visudo -cf "$sudoers_tmp"
sudo install -o root -g root -m 0440 "$sudoers_tmp" /etc/sudoers.d/doctrad2-runtime
printf '\nDOCTRAD2_SSH_ENROLLED\n'
printf 'Accès bc autorisé depuis 192.168.6.27 ; transfert de ports et terminal désactivés.\n'
printf 'Démarrage/arrêt/redémarrage du seul runtime DocTrad2 autorisés sans mot de passe.\n'
printf 'Aucun service redémarré ; aucune clé privée copiée.\n'
