if (-not (Test-Path "output")) {
    New-Item -ItemType Directory -Path "output"
}
$CurrentLocation = Get-Location
for ($temp = 0.01; $temp -le 100; $temp *= 100) {
    Start-Job -ScriptBlock {
        param ($temp, $CurrentLocation)
        Set-Location $CurrentLocation
        .\build\Debug\data_collector.exe --output_file "output/selfplay_15x15_data_temp_$temp.csv" `
                                          --temperature $temp `
                                          --log_file "logs/selfplay_15x15_temp_$temp.log" `
                                          --num_games 1000
    } -ArgumentList $temp, $CurrentLocation
}

# Wait for all jobs to finish
Get-Job | Wait-Job