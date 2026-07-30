

```
network: 
  version: 2
  renderer: networkd
  ethernets:
    end1:
      dhcp4: false
      dhcp6: false
      addresses:
      - 192.168.168.10/24
      - 10.0.0.37/24
      routes:
      - to: default
        via: 10.0.0.138
      nameservers:
       addresses: [8.8.8.8,8.8.4.4]
```