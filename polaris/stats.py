
class Stats:
    total_storage_size: int
    total_metadata_size: int
    original_data_size: int
    aggregated_data_size: int
    tmp_max_file_size_seen: int
    num_data_files: int
    largest_data_file: dict[str, float]
    smallest_data_file: dict[str, float]
    partitions_grid_file_size: int
    all_partition_metadata_files_total: int
    largest_metadata_file: dict[str, float]
    smallest_metadata_file: dict[str, float]

    def update(self, category: str):
        """
        Initial stats.json file looks as follows:

        {
            "totals": {
                "storage": 0,
                "metadata": 0
            },
            "storage": {
                "original": 0,
                "aggregated":0,
                "tmp_max": 0,
                "number_of_files": 0,
                "largest_file": {
                    "name": "",
                    "size": 0
                },
                "smallest_file": {
                    "name": "",
                    "size": 0
                }
            },
            "metadata": {
                "partitions_grid_file": 0,
                "partition_metadata_files_total": 0,
                "number_of_partitions": 0,
                "largest_partition_file": {
                    "name": "",
                    "size": 0
                },
                "smallest_partition_file": {
                    "name": "",
                    "size": 0
                }
            }
        }

        If any of the functions change the elements of the class,
        they will call this function and update the corresponding information
        """
        # Open stats.json file to edit it
        # Update information
        # Save and close file

    def add_to_size(self, category: str, addition: float) -> None:
        if category == "total storage":
            obj = self.total_storage_size
        elif category == "total metadata":
            obj = self.total_metadata_size
        elif category == "original data":
            obj = self.original_data_size
        elif category == "aggregated data":
            obj = self.aggregated_data_size

        obj += addition
        # NOTE: this will not update the actual object, so do this a different way

    def update_maxima(self, category: str, contenders: dict) -> None:
        # Category [] tells you which largest/smallest file size you will consider
        # Compare current largest file size with all file sizes in contenders
        #       if you find a larger one, 
        #           replace largest_[]_file with this new file name and size
        # Compare current smallest file size with all file sizes in contenders
        #       if you find a smaller one,
        #           replace smallest_[]_file with this new file name and size
        pass

    def update_count(self) -> None:
        self.num_data_files += 1

    def calculate_total_storage():
        pass

    def calculate_total_metadata():
        pass

    def calculate_file_size(self, file_name: str) -> None:
        pass

    def calculate_all_partition_metadata_files_size(self) -> None:
        pass